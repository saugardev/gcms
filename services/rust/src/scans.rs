use deadpool_postgres::Pool;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, error::Error};

pub struct Scan {
    pub time: f64,
    pub spectrum: Value,
    pub total: u64,
}

// Same complete ChemStation GC/MS layout validated by services/python/gcms/io.py.
// Preserve native m/z values (1/20 Da); no binning, smoothing or peak detection.
pub fn decode(raw: &[u8]) -> Result<Vec<Scan>, &'static str> {
    if raw.len() < 0x144
        || raw.len() > 64 * 1024 * 1024
        || raw[..4] != [1, 0x32, 0, 0]
        || raw.get(5..5 + raw[4] as usize) != Some(b"GC / MS Data File")
    {
        return Err("Expected a complete ChemStation GC/MS data.ms (maximum 64 MiB)");
    }
    let count = u16::from_le_bytes([raw[0x142], raw[0x143]]) as usize;
    let mut position = u16::from_be_bytes([raw[0x10a], raw[0x10b]]) as usize * 2;
    if !(7..=50_000).contains(&count) || position < 0x146 {
        return Err("Invalid scan count or data offset");
    }
    position -= 2;
    let mut scans: Vec<Scan> = Vec::with_capacity(count);
    let mut points = 0;
    for _ in 0..count {
        let header = raw
            .get(position..position + 18)
            .ok_or("Truncated scan header")?;
        let time = u32::from_be_bytes(header[2..6].try_into().unwrap()) as f64 / 1000.0;
        if scans.last().is_some_and(|last| time <= last.time) {
            return Err("Scan timestamps must increase");
        }
        let pairs = u16::from_be_bytes([header[12], header[13]]) as usize;
        points += pairs;
        let end = position + 28 + pairs * 4;
        if end > raw.len() || points > 12_000_000 {
            return Err("Truncated scan data or too many mass/intensity pairs");
        }
        let mut ions = BTreeMap::<u16, u64>::new();
        for pair in raw[position + 18..end - 10].chunks_exact(4) {
            let mass = u16::from_be_bytes([pair[0], pair[1]]);
            let encoded = u16::from_be_bytes([pair[2], pair[3]]);
            let intensity = (encoded as u64 & 0x3fff) << (3 * (encoded >> 14));
            *ions.entry(mass).or_default() += intensity;
        }
        scans.push(Scan {
            time,
            total: ions.values().sum(),
            spectrum: json!({
                "mz":ions.keys().map(|m| *m as f64 / 20.0).collect::<Vec<_>>(),
                "intensity":ions.values().collect::<Vec<_>>()
            }),
        });
        position = end;
    }
    if scans.iter().all(|scan| scan.total == 0) {
        return Err("The acquisition has no positive signal");
    }
    Ok(scans)
}

pub async fn import(pool: &Pool, id: &str, path: &str) -> Result<(), Box<dyn Error>> {
    if std::fs::metadata(path)?.len() > 64 * 1024 * 1024 {
        return Err("Acquisition exceeds 64 MiB".into());
    }
    let raw = std::fs::read(path)?;
    let hash = format!("{:x}", Sha256::digest(&raw));
    let mut client = pool.get().await?;
    let tx = client.transaction().await?;
    let row = tx
        .query_opt(
            "SELECT metadata FROM analyses WHERE id=$1 FOR UPDATE",
            &[&id],
        )
        .await?
        .ok_or("Import the saved analysis first")?;
    let metadata: Value = row.get(0);
    if metadata["provenance"]["input_data_ms_sha256"] != hash {
        return Err("Acquisition SHA-256 does not match this saved analysis".into());
    }
    if tx
        .query_opt(
            "SELECT analysis_id FROM raw_acquisitions WHERE analysis_id=$1",
            &[&id],
        )
        .await?
        .is_some()
    {
        println!("{}", json!({"id":id,"imported":false}));
        return Ok(());
    }
    let scans = decode(&raw)?;
    let acquisition = &metadata["acquisition"];
    if acquisition["scan_count"].as_u64() != Some(scans.len() as u64)
        || acquisition["start_seconds"]
            .as_f64()
            .is_none_or(|v| (v - scans[0].time).abs() > 1e-6)
        || acquisition["end_seconds"]
            .as_f64()
            .is_none_or(|v| (v - scans.last().unwrap().time).abs() > 1e-6)
    {
        return Err("Scan count or times differ from the saved analysis".into());
    }
    let trace = json!({"time_seconds":scans.iter().map(|s|s.time).collect::<Vec<_>>(),
        "raw_tic":scans.iter().map(|s|s.total).collect::<Vec<_>>()});
    tx.execute(
        "INSERT INTO raw_acquisitions (analysis_id,source_sha256,chromatogram) VALUES ($1,$2,$3)",
        &[&id, &hash, &trace],
    )
    .await?;
    let statement = tx.prepare("INSERT INTO raw_scans (analysis_id,scan_index,time_seconds,spectrum) VALUES ($1,$2,$3,$4)").await?;
    for (index, scan) in scans.iter().enumerate() {
        tx.execute(
            &statement,
            &[&id, &(index as i32), &scan.time, &scan.spectrum],
        )
        .await?;
    }
    tx.commit().await?;
    println!("{}", json!({"id":id,"imported":true,"scans":scans.len()}));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn raw_scans_preserve_native_masses_and_validate_complete_records() {
        let mut raw = vec![0; 0x144];
        raw[..4].copy_from_slice(&[1, 0x32, 0, 0]);
        raw[4] = 17;
        raw[5..22].copy_from_slice(b"GC / MS Data File");
        raw[0x142..0x144].copy_from_slice(&7_u16.to_le_bytes());
        raw[0x10a..0x10c].copy_from_slice(&163_u16.to_be_bytes());
        for index in 0..7_u32 {
            let mut scan = vec![0; 40];
            scan[2..6].copy_from_slice(&(1000 + index * 200).to_be_bytes());
            scan[12..14].copy_from_slice(&3_u16.to_be_bytes());
            for (i, (mz, intensity)) in [(861_u16, 0x4002_u16), (800, 3), (861, 1)]
                .iter()
                .enumerate()
            {
                scan[18 + i * 4..20 + i * 4].copy_from_slice(&mz.to_be_bytes());
                scan[20 + i * 4..22 + i * 4].copy_from_slice(&intensity.to_be_bytes());
            }
            raw.extend(scan);
        }
        let scans = decode(&raw).unwrap();
        assert_eq!(scans.len(), 7);
        assert_eq!(scans[6].time, 2.2);
        assert_eq!(
            scans[0].spectrum,
            json!({"mz":[40.0,43.05],"intensity":[3,17]})
        );
        assert_eq!(scans[0].total, 20);
        assert!(decode(&raw[..raw.len() - 1]).is_err());
        raw[0x144 + 40 + 2..0x144 + 40 + 6].copy_from_slice(&1000_u32.to_be_bytes());
        assert!(decode(&raw).is_err());
        assert!(decode(&[]).is_err());
    }
}
