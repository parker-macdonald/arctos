//! IndexedDB-backed queue for record page uploads. Single store keyed by sequence;
//! key order is queue order. Rebuild in-memory queue on load by cursoring in key order.

#![cfg(target_arch = "wasm32")]

use crate::api::RecordChunkMeta;
use idb::{Database, Query, TransactionMode};
use js_sys::{Object, Reflect};
use wasm_bindgen::{JsCast, JsValue};

const DB_NAME: &str = "arctos_record_queue";
const STORE_NAME: &str = "queue";
const RESERVED_KEY_NEXT: &str = "z_next";
const SEQ_PADDING: usize = 8;

/// Open the record queue database (creates store on first run).
pub async fn open_db() -> Result<Database, idb::Error> {
    let store = idb::ObjectStore::builder(STORE_NAME).key_path(None);
    Database::builder(DB_NAME)
        .version(1)
        .add_object_store(store)
        .build()
        .await
}

/// Reserve next sequence key, increment stored counter, return the key used (zero-padded).
pub async fn get_next_sequence(db: &Database) -> Result<String, idb::Error> {
    let tx = db.transaction(&[STORE_NAME], TransactionMode::ReadWrite)?;
    let store = tx.object_store(STORE_NAME)?;

    let key_js = JsValue::from_str(RESERVED_KEY_NEXT);
    let current: Option<JsValue> = store.get(Query::from(key_js.clone()))?.await?;
    let next_num: u32 = current
        .and_then(|v| v.as_f64())
        .map(|f| f as u32)
        .unwrap_or(0)
        .saturating_add(1);

    // Return key for this enqueue (next_num - 1), store next_num for next time
    let this_key = format!("{:0>width$}", next_num.saturating_sub(1), width = SEQ_PADDING);
    let num_js = JsValue::from(next_num as f64);
    store.put(&num_js, Some(&key_js))?;
    tx.await?;
    Ok(this_key)
}

/// Put a chunk entry (meta + blob) under the given sequence key.
pub async fn put_chunk(
    db: &Database,
    key: &str,
    meta: &RecordChunkMeta,
    blob: &web_sys::Blob,
) -> Result<(), idb::Error> {
    let obj = build_chunk_value(meta, blob);
    put_entry(db, key, &obj).await
}

/// Put a finalize entry under the given sequence key.
pub async fn put_finalize(db: &Database, key: &str, match_id: &str) -> Result<(), idb::Error> {
    let obj = Object::new();
    let _ = Reflect::set(&obj, &"type".into(), &"finalize".into());
    let _ = Reflect::set(&obj, &"match_id".into(), &JsValue::from_str(match_id));
    put_entry(db, key, &JsValue::from(obj)).await
}

async fn put_entry(db: &Database, key: &str, value: &JsValue) -> Result<(), idb::Error> {
    let tx = db.transaction(&[STORE_NAME], TransactionMode::ReadWrite)?;
    let store = tx.object_store(STORE_NAME)?;
    let key_js = JsValue::from_str(key);
    store.put(value, Some(&key_js))?.await?;
    tx.await?;
    Ok(())
}

/// Get an entry by key. Returns (key, value) where value is the raw JsValue (chunk object or finalize object).
pub async fn get_entry(db: &Database, key: &str) -> Result<Option<JsValue>, idb::Error> {
    let tx = db.transaction(&[STORE_NAME], TransactionMode::ReadOnly)?;
    let store = tx.object_store(STORE_NAME)?;
    let key_js = JsValue::from_str(key);
    let value = store.get(Query::from(key_js))?.await?;
    tx.await?;
    Ok(value)
}

/// Delete an entry by key.
pub async fn delete_entry(db: &Database, key: &str) -> Result<(), idb::Error> {
    let tx = db.transaction(&[STORE_NAME], TransactionMode::ReadWrite)?;
    let store = tx.object_store(STORE_NAME)?;
    let key_js = JsValue::from_str(key);
    store.delete(Query::from(key_js))?.await?;
    tx.await?;
    Ok(())
}

/// Sum of [`web_sys::Blob::size`] for all chunk entries (finalize rows excluded). Used so preview
/// metadata reflects the recording queue when `navigator.storage.estimate()` under-reports IDB.
pub async fn sum_chunk_blob_bytes(db: &Database) -> Result<u64, idb::Error> {
    let entries = cursor_entries_ordered(db).await?;
    let mut total: u64 = 0;
    for (_, value) in entries {
        if let Some((_, blob)) = parse_chunk_value(&value) {
            let s = blob.size();
            if s.is_finite() && s >= 0.0 {
                total = total.saturating_add(s as u64);
            }
        }
    }
    Ok(total)
}

/// Cursor over entries in key order (from "00000000" up to but not including "z_next").
/// Returns (key, value) pairs for rebuilding the in-memory queue.
pub async fn cursor_entries_ordered(db: &Database) -> Result<Vec<(String, JsValue)>, idb::Error> {
    let lower = JsValue::from_str("00000000");
    let upper = JsValue::from_str(RESERVED_KEY_NEXT);
    let range = idb::KeyRange::bound(&lower, &upper, Some(true), Some(true))?; // lower inclusive, upper exclusive
    let query = Some(Query::from(range));
    let tx = db.transaction(&[STORE_NAME], TransactionMode::ReadOnly)?;
    let store = tx.object_store(STORE_NAME)?;
    let keys: Vec<JsValue> = store.get_all_keys(query.clone(), None)?.await?;
    let values: Vec<JsValue> = store.get_all(query, None)?.await?;
    tx.await?;
    let mut out = Vec::with_capacity(keys.len());
    for (k, v) in keys.into_iter().zip(values.into_iter()) {
        if let Some(s) = k.as_string() {
            if s != RESERVED_KEY_NEXT {
                out.push((s, v));
            }
        }
    }
    Ok(out)
}

fn build_chunk_value(meta: &RecordChunkMeta, blob: &web_sys::Blob) -> JsValue {
    let obj = Object::new();
    let _ = Reflect::set(&obj, &"type".into(), &"chunk".into());
    let _ = Reflect::set(&obj, &"blob".into(), blob);
    let meta_obj = meta_to_js(meta);
    let _ = Reflect::set(&obj, &"meta".into(), &meta_obj);
    obj.into()
}

fn meta_to_js(meta: &RecordChunkMeta) -> JsValue {
    let o = Object::new();
    let _ = Reflect::set(&o, &"tournament_url".into(), &JsValue::from_str(&meta.tournament_url));
    let _ = Reflect::set(&o, &"field".into(), &JsValue::from_str(&meta.field));
    let _ = Reflect::set(&o, &"match_id".into(), &JsValue::from_str(&meta.match_id));
    let _ = Reflect::set(&o, &"session_id".into(), &JsValue::from_str(&meta.session_id));
    let _ = Reflect::set(
        o.as_ref(),
        &"chunk_start_timestamp".into(),
        &JsValue::from_f64(meta.chunk_start_timestamp),
    );
    let _ = Reflect::set(
        o.as_ref(),
        &"recording_session_start_time".into(),
        &JsValue::from_f64(meta.recording_session_start_time),
    );
    let _ = Reflect::set(
        o.as_ref(),
        &"chunk_length_ms".into(),
        &JsValue::from_f64(meta.chunk_length_ms as f64),
    );
    let _ = Reflect::set(&o, &"camera_name".into(), &JsValue::from_str(&meta.camera_name));
    if let Some(ref k) = meta.key {
        let _ = Reflect::set(o.as_ref(), &"key".into(), &JsValue::from_str(k));
    }
    let _ = Reflect::set(&o, &"container".into(), &JsValue::from_str(&meta.container));
    let _ = Reflect::set(
        o.as_ref(),
        &"blob_event_timestamp_ms".into(),
        &JsValue::from_f64(meta.blob_event_timestamp_ms),
    );
    let _ = Reflect::set(
        o.as_ref(),
        &"keyframe_wall_times_json".into(),
        &JsValue::from_str(&meta.keyframe_wall_times_json),
    );
    o.into()
}

/// Parse a chunk value from IDB back into RecordChunkMeta and blob. Returns None if type is not "chunk".
pub fn parse_chunk_value(value: &JsValue) -> Option<(RecordChunkMeta, web_sys::Blob)> {
    let type_str = Reflect::get(value, &"type".into()).ok()?.as_string()?;
    if type_str != "chunk" {
        return None;
    }
    let meta_js = Reflect::get(value, &"meta".into()).ok()?;
    let blob_js = Reflect::get(value, &"blob".into()).ok()?;
    let blob = blob_js.dyn_ref::<web_sys::Blob>().map(|b| b.clone())?;
    let meta = js_to_meta(&meta_js)?;
    Some((meta, blob))
}

/// Parse a finalize value, return match_id if type is "finalize".
pub fn parse_finalize_value(value: &JsValue) -> Option<String> {
    let type_str = Reflect::get(value, &"type".into()).ok()?.as_string()?;
    if type_str != "finalize" {
        return None;
    }
    Reflect::get(value, &"match_id".into())
        .ok()?
        .as_string()
}

fn js_to_meta(js: &JsValue) -> Option<RecordChunkMeta> {
    Some(RecordChunkMeta {
        tournament_url: Reflect::get(js, &"tournament_url".into()).ok()?.as_string()?,
        field: Reflect::get(js, &"field".into()).ok()?.as_string()?,
        match_id: Reflect::get(js, &"match_id".into()).ok()?.as_string()?,
        session_id: Reflect::get(js, &"session_id".into()).ok()?.as_string()?,
        chunk_start_timestamp: Reflect::get(js, &"chunk_start_timestamp".into())
            .ok()?
            .as_f64()?,
        recording_session_start_time: Reflect::get(js, &"recording_session_start_time".into())
            .ok()?
            .as_f64()?,
        chunk_length_ms: Reflect::get(js, &"chunk_length_ms".into())
            .ok()?
            .as_f64()
            .map(|f| f as u32)?,
        camera_name: Reflect::get(js, &"camera_name".into()).ok()?.as_string()?,
        key: Reflect::get(js, &"key".into()).ok().and_then(|v| v.as_string()),
        container: Reflect::get(js, &"container".into())
            .ok()?
            .as_string()
            .unwrap_or_else(|| "webm".to_string()),
        blob_event_timestamp_ms: Reflect::get(js, &"blob_event_timestamp_ms".into())
            .ok()
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0),
        keyframe_wall_times_json: Reflect::get(js, &"keyframe_wall_times_json".into())
            .ok()
            .and_then(|v| v.as_string())
            .unwrap_or_else(|| "[]".to_string()),
    })
}
