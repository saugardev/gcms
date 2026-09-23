use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::HashSet;

pub struct SavedAnalysis {
    pub id: String,
    pub name: String,
    pub metadata: Value,
    pub chromatogram: Value,
    pub peaks: Value,
    pub components: Vec<(String, Value)>,
}

fn number(value: &Value) -> Result<f64, String> {
    value
        .as_f64()
        .filter(|n| n.is_finite())
        .ok_or("Expected a finite number".into())
}

fn array(value: &Value) -> Result<&Vec<Value>, String> {
    value.as_array().ok_or("Expected an array".into())
}

fn aligned(x: &Value, y: &Value) -> Result<(), String> {
    let (x, y) = (array(x)?, array(y)?);
    if x.len() != y.len() {
        return Err("Mismatched plot arrays".into());
    }
    let mut previous = f64::NEG_INFINITY;
    for (x, y) in x.iter().zip(y) {
        let x = number(x)?;
        if x <= previous || number(y)? < 0.0 {
            return Err("Invalid plot axes or intensity".into());
        }
        previous = x;
    }
    Ok(())
}

fn spectrum(value: &Value) -> Result<(), String> {
    aligned(&value["mz"], &value["intensity"])
}

fn strings(value: &Value) -> bool {
    value
        .as_array()
        .is_some_and(|a| a.iter().all(Value::is_string))
}

pub fn parse(bytes: &[u8]) -> Result<SavedAnalysis, String> {
    let document: Value = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
    let review = document.get("analysis").is_some();
    if review && document["schema_version"] != "review-1.0" {
        return Err("Unsupported review schema".into());
    }
    let report = if review {
        &document["analysis"]
    } else {
        &document
    };
    if report["schema_version"] != "1.0"
        || !report["provenance"]["software"]["gcms-rust"].is_string()
    {
        return Err("Import a saved schema 1.0 report produced by the Rust engine".into());
    }
    let name = report["sample_name"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("Missing sample name")?
        .to_owned();
    for field in ["input_data_ms_sha256", "library_sha256"] {
        let hash = report["provenance"][field]
            .as_str()
            .ok_or("Missing provenance hash")?;
        if hash.len() != 64 || !hash.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err("Invalid provenance hash".into());
        }
    }
    if !report["parameters"].is_object()
        || !strings(&report["warnings"])
        || !report["algorithm_version"].is_string()
    {
        return Err("Missing analysis parameters or provenance".into());
    }
    for key in [
        "scan_count",
        "mass_channel_count",
        "start_seconds",
        "end_seconds",
        "mz_min",
        "mz_max",
    ] {
        number(&report["acquisition"][key])?;
    }
    let chromatogram = &report["chromatogram"];
    if array(&chromatogram["time_seconds"])?.len() < 2 {
        return Err("Chromatogram needs at least two points".into());
    }
    for key in ["raw_tic", "corrected_tic"] {
        aligned(&chromatogram["time_seconds"], &chromatogram[key])?;
    }
    let components = array(&report["components"])?;
    if components.len() > 1000
        || report["summary"]["component_count"].as_u64() != Some(components.len() as u64)
    {
        return Err("Invalid component count (maximum 1000)".into());
    }
    let mut ids = HashSet::new();
    let mut peaks = Vec::new();
    let mut stored = Vec::new();
    for component in components {
        let id = component["component_id"]
            .as_str()
            .ok_or("Missing component ID")?;
        if !id
            .strip_prefix("component-")
            .is_some_and(|s| s.len() == 4 && s.bytes().all(|b| b.is_ascii_digit()))
            || !ids.insert(id)
        {
            return Err("Invalid or duplicate component ID".into());
        }
        let start = number(&component["start_seconds"])?;
        let apex = number(&component["apex_seconds"])?;
        let end = number(&component["end_seconds"])?;
        if start > apex
            || apex > end
            || number(&component["area"])? < 0.0
            || number(&component["area_percent"])? < 0.0
        {
            return Err("Invalid component bounds or area".into());
        }
        if !matches!(
            component["status"].as_str(),
            Some("tentative" | "ambiguous" | "unassigned")
        ) {
            return Err("Invalid component status".into());
        }
        spectrum(&component["spectrum"])?;
        if !strings(&component["warnings"]) {
            return Err("Invalid component warnings".into());
        }
        let candidates = array(&component["candidates"])?;
        let mut search = vec![id.to_owned()];
        for candidate in candidates {
            if !candidate["group_id"].is_string() || array(&candidate["identities"])?.is_empty() {
                return Err("Missing candidate group or identities".into());
            }
            if !(0.0..=1.0).contains(&number(&candidate["score"])?) {
                return Err("Invalid similarity".into());
            }
            spectrum(&candidate["reference_spectrum"])?;
            for identity in array(&candidate["identities"])? {
                search.push(
                    identity["name"]
                        .as_str()
                        .ok_or("Missing candidate name")?
                        .to_owned(),
                );
                if let Some(cas) = identity["cas"].as_str() {
                    search.push(cas.to_owned());
                }
            }
        }
        let annotation = if review {
            document["annotations"]
                .get(id)
                .cloned()
                .ok_or("Missing review annotation")?
        } else {
            Value::Null
        };
        if review {
            if !annotation["label"].is_string() {
                return Err("Missing review label".into());
            }
            let trace = &annotation["trace"];
            for key in ["raw_tic", "corrected_tic", "component_ion_sum"] {
                aligned(&trace["time_seconds"], &trace[key])?;
            }
            for ion in array(&trace["ions"])? {
                number(&ion["mz"])?;
                aligned(&trace["time_seconds"], &ion["intensity"])?;
            }
        }
        let top_names: Vec<&str> = candidates
            .first()
            .and_then(|c| c["identities"].as_array())
            .into_iter()
            .flatten()
            .filter_map(|i| i["name"].as_str())
            .collect();
        peaks.push(json!({
            "component_id":id, "apex_seconds":apex, "start_seconds":start, "end_seconds":end,
            "area_percent":component["area_percent"], "status":component["status"],
            "name":top_names.join(" / "), "score":candidates.first().map(|c| &c["score"]),
            "stability":annotation["label"], "search_text":search.join(" ")
        }));
        stored.push((
            id.to_owned(),
            json!({"component":component,"review":annotation}),
        ));
    }
    peaks.sort_by(|a, b| {
        a["apex_seconds"]
            .as_f64()
            .unwrap()
            .total_cmp(&b["apex_seconds"].as_f64().unwrap())
            .then_with(|| a["component_id"].as_str().cmp(&b["component_id"].as_str()))
    });
    let mut metadata = report
        .as_object()
        .ok_or("Expected a report object")?
        .clone();
    metadata.remove("components");
    metadata.remove("chromatogram");
    if review {
        metadata.insert("review".into(),json!({"summary":document["summary"],"method":document["method"],"variants":document["variants"],"warnings":document["warnings"]}));
    }
    let id = format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&document).map_err(|e| e.to_string())?)
    );
    Ok(SavedAnalysis {
        id,
        name,
        metadata: Value::Object(metadata),
        chromatogram: chromatogram.clone(),
        peaks: json!(peaks),
        components: stored,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn saved_rust_report_is_validated_and_identity_is_stable() {
        let mut value = json!({"schema_version":"1.0","sample_name":"test","algorithm_version":"coapex-1","parameters":{},"warnings":[],"provenance":{"software":{"gcms-rust":"0.1.0"},"input_data_ms_sha256":"a".repeat(64),"library_sha256":"b".repeat(64)},"acquisition":{"scan_count":2,"mass_channel_count":1,"start_seconds":0,"end_seconds":1,"mz_min":43,"mz_max":43},"summary":{"component_count":0},"components":[],"chromatogram":{"time_seconds":[0,1],"raw_tic":[0,1],"corrected_tic":[0,1]}});
        let report = parse(&serde_json::to_vec(&value).unwrap()).unwrap();
        // Saved scientific values must survive JSON -> PostgreSQL -> JSON unchanged.
        let decimal: Value = serde_json::from_str("188527.60000000006").unwrap();
        assert_eq!(decimal.as_f64().unwrap(), 188527.60000000006_f64);
        assert_eq!(
            report.id,
            parse(&serde_json::to_vec_pretty(&value).unwrap())
                .unwrap()
                .id
        );
        value["summary"]["component_count"] = json!(1);
        value["components"] = json!([{
            "component_id":"component-0001", "start_seconds":0, "apex_seconds":0.5,
            "end_seconds":1, "area":5, "area_percent":100, "status":"tentative",
            "warnings":[], "spectrum":{"mz":[43,44],"intensity":[10,5]},
            "candidates":[{"group_id":"group-1", "score":0.9,
                "identities":[{"name":"Test","cas":"1-2-3"}],
                "reference_spectrum":{"mz":[43,44],"intensity":[100,50]}}]
        }]);
        let populated = parse(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert_eq!(populated.peaks[0]["name"], "Test");
        assert_eq!(
            populated.components[0].1["component"],
            value["components"][0]
        );
        let mut invalid = value.clone();
        invalid["components"][0]["spectrum"]["intensity"] = json!([10]);
        assert!(parse(&serde_json::to_vec(&invalid).unwrap()).is_err());
        value["chromatogram"]["time_seconds"] = json!([1, 0]);
        assert!(parse(&serde_json::to_vec(&value).unwrap()).is_err());
        value["chromatogram"]["time_seconds"] = json!([0, 1]);
        value["provenance"]["software"] = json!({"python":"3.12"});
        assert!(parse(&serde_json::to_vec(&value).unwrap()).is_err());
    }
}
