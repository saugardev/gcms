"""Bounded instrument/ZIP ingestion and validated MSP parsing."""

import hashlib
import os
import re
import stat
import struct
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np
from rainbow.agilent.chemstation import parse_ms

from .models import Identity, ProcessingError

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_CELLS = 12_000_000
DEFAULT_LIBRARY = Path(os.environ["GCMS_LIBRARY"]) if os.getenv("GCMS_LIBRARY") else None
DEFAULT_SAMPLE = Path(os.environ["GCMS_SAMPLE"]) if os.getenv("GCMS_SAMPLE") else None


@dataclass
class Run:
    time_seconds: np.ndarray
    mz: np.ndarray
    intensity: np.ndarray
    name: str
    source_sha256: str
    metadata: dict

    def validate(self):
        t, mz, y = self.time_seconds, self.mz, self.intensity
        if t.ndim != 1 or mz.ndim != 1 or y.shape != (len(t), len(mz)):
            raise ProcessingError("invalid_arrays", "Expected intensity[scan, mass] and 1D axes.")
        if len(t) < 7 or len(mz) < 2 or y.size > MAX_CELLS:
            raise ProcessingError(
                "unsupported_dimensions", "Run is too small or exceeds cell limit."
            )
        if not all(np.isfinite(a).all() for a in (t, mz, y)) or np.any(y < 0):
            raise ProcessingError("invalid_values", "Axes must be finite; intensity nonnegative.")
        if np.any(np.diff(t) <= 0) or np.any(np.diff(mz) != 1) or np.any(mz != np.rint(mz)):
            raise ProcessingError(
                "invalid_axes", "Require increasing times and a nominal 1 Da grid."
            )
        dt = np.diff(t)
        if np.max(np.abs(dt - np.median(dt))) > 0.05 * np.median(dt):
            raise ProcessingError("irregular_scans", "Scan intervals vary by more than 5%.")
        if not np.any(y):
            raise ProcessingError("empty_signal", "The run contains no positive signal.")


@dataclass
class Library:
    identities: list[list[Identity]]
    spectra: list[np.ndarray]
    sha256: str
    audit: dict

    def project(self, mz: np.ndarray):
        """Project references onto the acquisition range; keep absent ions at zero."""
        matrix = np.zeros((len(self.spectra), len(mz)), dtype=np.float64)
        fractions = np.zeros(len(self.spectra))
        for i, peaks in enumerate(self.spectra):
            bins = np.rint(peaks[:, 0]).astype(np.int64) - int(mz[0])
            valid = (bins >= 0) & (bins < len(mz))
            np.add.at(matrix[i], bins[valid], peaks[valid, 1])
            fractions[i] = matrix[i].sum() / peaks[:, 1].sum()
        return matrix, fractions


def read_library(path: Path) -> Library:
    raw = path.read_bytes()
    groups, spectra, identities = {}, [], []
    rt_values = set()
    try:
        blocks = re.split(r"\n\s*\n", raw.decode("utf-8-sig").replace("\r\n", "\n").strip())
        entry_count = 0
        for block in blocks:
            lines = block.splitlines()
            meta, peak_lines = {}, []
            reading_peaks = False
            for line in lines:
                if reading_peaks:
                    peak_lines.append(line)
                elif ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip().lower()] = value.strip()
                    reading_peaks = key.strip().lower() == "num peaks"
                elif line.strip():
                    raise ValueError("Expected a metadata field before Num Peaks")
            if not meta.get("name") or not reading_peaks:
                raise ValueError("Each entry requires Name and Num Peaks")
            tokens = re.split(r"[\s;]+", " ".join(peak_lines).strip().rstrip(";"))
            if len(tokens) % 2:
                raise ValueError("Mass/intensity pairs must have an even number of values")
            peaks = np.array([float(x) for x in tokens], dtype=np.float64).reshape(-1, 2)
            if len(peaks) != int(meta["num peaks"]):
                raise ValueError("Num Peaks does not match the number of pairs")
            if not np.isfinite(peaks).all() or np.any(peaks < 0) or not np.any(peaks[:, 1] > 0):
                raise ValueError("Require finite nonnegative peaks and positive total intensity")
            peaks = peaks[np.lexsort((peaks[:, 1], peaks[:, 0]))]
            identity = Identity(
                entry_id=f"entry-{entry_count + 1:04d}",
                name=meta["name"],
                source=meta.get("library"),
                cas=meta.get("cas#"),
                formula=meta.get("formula"),
                molecular_weight=_optional_number(meta.get("mw")),
                reference_rt=_optional_number(meta.get("rt")),
                reference_ri=_optional_number(meta.get("ri")),
            )
            key = peaks.astype("<f8").tobytes()
            if key not in groups:
                groups[key] = len(spectra)
                spectra.append(peaks)
                identities.append([])
            identities[groups[key]].append(identity)
            entry_count += 1
            rt_values.add(meta.get("rt"))
        if not entry_count:
            raise ValueError("Library has no entries")
    except (ValueError, UnicodeError, IndexError) as exc:
        raise ProcessingError("invalid_library", f"Cannot parse MSP library: {exc}") from exc
    duplicates = [g for g in identities if len(g) > 1]
    audit = {
        "entries": entry_count,
        "spectrum_groups": len(spectra),
        "exact_duplicate_groups": len(duplicates),
        "duplicate_groups_with_different_names": sum(
            len({i.name for i in g}) > 1 for g in duplicates
        ),
        "duplicate_groups_with_different_cas": sum(
            len({i.cas for i in g if i.cas}) > 1 for g in duplicates
        ),
        "distinct_reference_rt_values": len(rt_values),
        "sources": dict(Counter(i.source or "unspecified" for g in identities for i in g)),
    }
    return Library(identities, spectra, hashlib.sha256(raw).hexdigest(), audit)


def _optional_number(value):
    if value is None:
        return None
    number = float(value)
    if not np.isfinite(number) or number < 0:
        raise ValueError("Invalid numeric library metadata")
    return number


def read_run(path: Path) -> Run:
    if path.is_dir():
        matches = [p for p in path.iterdir() if p.name.lower() == "data.ms" and p.is_file()]
        if len(matches) != 1:
            raise ProcessingError("missing_data_ms", "The .D directory must contain one data.ms.")
        source = matches[0]
        name = path.stem
    else:
        source, name = path, path.stem
    if source.stat().st_size > MAX_UPLOAD_BYTES:
        raise ProcessingError("sample_too_large", "data.ms exceeds 64 MiB.", 413)
    raw = source.read_bytes()
    times, totals = _validate_ms(raw)
    try:
        data = parse_ms(str(source), display_precision=0, bin_width=1.0)
        observed_mz = np.asarray(data.ylabels, dtype=np.float64)
        mz = np.arange(observed_mz.min(), observed_mz.max() + 1, dtype=np.float64)
        y = np.zeros((len(times), len(mz)), dtype=np.float64)
        y[:, (observed_mz - mz[0]).astype(int)] = data.data
        if not np.array_equal(y.sum(axis=1), totals):
            raise ValueError("Decoded ion totals differ from raw scan totals")
        if not np.allclose(np.asarray(data.xlabels) * 60, times, atol=1e-9, rtol=0):
            raise ValueError("Decoded timestamps differ from raw timestamps")
    except Exception as exc:
        raise ProcessingError(
            "invalid_ms_data", "Cannot decode the complete GC/MS data.ms file."
        ) from exc
    run = Run(times, mz, y, name, hashlib.sha256(raw).hexdigest(), data.metadata)
    run.validate()
    return run


def _validate_ms(raw: bytes):
    """Bound allocations and reject partial files before calling the vendor reader."""
    try:
        if len(raw) < 0x144 or raw[:4] != b"\x01\x32\x00\x00":
            raise ValueError("Invalid complete ChemStation header")
        if raw[5 : 5 + raw[4]] != b"GC / MS Data File":
            raise ValueError("Only GC / MS Data File acquisition is supported")
        count = struct.unpack_from("<H", raw, 0x142)[0]
        position = struct.unpack_from(">H", raw, 0x10A)[0] * 2 - 2
        if not 7 <= count <= 50_000 or position < 0x144:
            raise ValueError("Invalid scan count or data offset")
        times, totals = np.empty(count), np.empty(count)
        low, high = 3277, 0
        for i in range(count):
            if position + 18 > len(raw):
                raise ValueError("Truncated scan header")
            times[i] = struct.unpack_from(">I", raw, position + 2)[0] / 1000
            pairs = struct.unpack_from(">H", raw, position + 12)[0]
            end = position + 28 + pairs * 4
            if end > len(raw):
                raise ValueError("Truncated scan data")
            values = np.frombuffer(raw, dtype=">u2", count=pairs * 2, offset=position + 18)
            if pairs:
                masses = np.rint(values[::2].astype(float) / 20)
                low, high = min(low, masses.min()), max(high, masses.max())
            encoded = values[1::2].astype(np.uint64)
            totals[i] = np.sum((encoded & 0x3FFF) << (3 * (encoded >> 14)), dtype=np.uint64)
            position = end
        if high <= low or count * (high - low + 1) > MAX_CELLS:
            raise ValueError("Mass grid exceeds the supported dimensions")
        if np.any(np.diff(times) <= 0):
            raise ValueError("Scan timestamps must increase")
        return times, totals
    except (ValueError, struct.error) as exc:
        raise ProcessingError("invalid_ms_data", str(exc)) from exc


def extract_sample(archive_path: Path, destination: Path) -> Path:
    """Validate the whole ZIP and extract only data.ms; never use extractall."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if len(entries) > 512 or sum(e.file_size for e in entries) > MAX_EXPANDED_BYTES:
                raise ProcessingError(
                    "archive_too_large", "ZIP exceeds 512 entries or 128 MiB.", 413
                )
            seen, roots, samples = set(), set(), []
            for entry in entries:
                name = entry.orig_filename
                path = PurePosixPath(name)
                if (
                    not name
                    or "\x00" in name
                    or "\\" in name
                    or ":" in name
                    or path.is_absolute()
                    or ".." in path.parts
                    or len(name) > 512
                    or any(len(part.encode("utf-8")) > 255 for part in path.parts)
                ):
                    raise ProcessingError("unsafe_archive", "ZIP contains an unsafe path.")
                if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    raise ProcessingError(
                        "unsafe_archive", "ZIP symlinks and encryption are unsupported."
                    )
                if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ProcessingError("invalid_zip", "Use stored or deflated ZIP compression.")
                key = str(path).lower()
                if key in seen:
                    raise ProcessingError("unsafe_archive", "ZIP contains duplicate paths.")
                seen.add(key)
                for i, part in enumerate(path.parts):
                    if part.lower().endswith(".d"):
                        roots.add(str(PurePosixPath(*path.parts[: i + 1])).lower())
                if (
                    not entry.is_dir()
                    and path.name.lower() == "data.ms"
                    and path.parent.name.lower().endswith(".d")
                ):
                    samples.append((entry, path))
            if len(roots) != 1 or len(samples) != 1:
                raise ProcessingError(
                    "invalid_sample_layout",
                    "ZIP must contain exactly one .D directory with data.ms.",
                )
            entry, path = samples[0]
            if entry.file_size > MAX_UPLOAD_BYTES:
                raise ProcessingError("sample_too_large", "data.ms exceeds 64 MiB.", 413)
            output = destination / path.parent.name
            output.mkdir()
            with archive.open(entry) as source, (output / "data.ms").open("wb") as target:
                total = 0
                while chunk := source.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES:
                        raise ProcessingError("sample_too_large", "data.ms exceeds 64 MiB.", 413)
                    target.write(chunk)
            return output
    except (zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError, EOFError) as exc:
        raise ProcessingError(
            "invalid_zip", "Cannot read ZIP; use an unencrypted ZIP archive."
        ) from exc
