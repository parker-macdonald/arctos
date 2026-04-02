//! Minimal fMP4 parsing for MediaRecorder chunks (strict assumptions).
//!
//! - One `moof` + one `mdat` per fragment after init, or `ftyp`+`moov` init segment.
//! - One `traf`/`trun` per `moof`; sync samples: `sample_is_non_sync` bit clear in `sample_flags`
//!   (ISO 14496-12: bit 16 of sample_flags = is_non_sync_sample).
//! - Timescale from `moov/mdhd` when present in the same buffer or from `cached_timescale`.

fn read_u32_be(b: &[u8], i: usize) -> Option<u32> {
    b.get(i..i + 4)?.try_into().ok().map(u32::from_be_bytes)
}

fn read_u64_be(b: &[u8], i: usize) -> Option<u64> {
    b.get(i..i + 8)?.try_into().ok().map(u64::from_be_bytes)
}

fn fourcc(b: &[u8], i: usize) -> Option<[u8; 4]> {
    b.get(i..i + 4)?.try_into().ok()
}

/// Walk top-level boxes; `cb` receives (box_type, payload range inside `data`).
fn walk_boxes<F: FnMut([u8; 4], std::ops::Range<usize>)>(data: &[u8], mut cb: F) {
    let mut i = 0usize;
    while i + 8 <= data.len() {
        let sz = read_u32_be(data, i).unwrap_or(0) as usize;
        if sz < 8 {
            break;
        }
        let end = i.saturating_add(sz).min(data.len());
        let typ = fourcc(data, i + 4).unwrap_or([0, 0, 0, 0]);
        let payload = (i + 8)..end;
        cb(typ, payload);
        i = end;
    }
}

/// Extract concatenation of `ftyp` and `moov` boxes from a buffer (if present).
pub fn extract_ftyp_moov(data: &[u8]) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    walk_boxes(data, |typ, r| {
        if typ == *b"ftyp" || typ == *b"moov" {
            out.extend_from_slice(&data[r.start - 8..r.end]);
        }
    });
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

/// Read `timescale` from `moov/trak/mdia/mdhd` (first track only).
pub fn timescale_from_moov(moov_payload: &[u8]) -> Option<u32> {
    let mut found = None;
    walk_boxes(moov_payload, |typ, r| {
        if typ == *b"trak" {
            walk_boxes(&moov_payload[r.clone()], |t2, r2| {
                if t2 == *b"mdia" {
                    walk_boxes(&moov_payload[r2.clone()], |t3, r3| {
                        if t3 == *b"mdhd" && r3.end >= r3.start + 20 {
                            let off = r3.start + 12;
                            if let Some(ts) = read_u32_be(moov_payload, off) {
                                found = Some(ts);
                            }
                        }
                    });
                }
            });
        }
    });
    found
}

#[derive(Clone, Debug)]
pub struct SyncSampleWall {
    pub wall_epoch_ms: f64,
    pub sample_index_in_fragment: u32,
}

/// Parse fragment `data` (moof+mdat or init+moof+mdat). `chunk_wall_epoch_ms` approximates wall time
/// for the first sample in this fragment (`dts0`).
pub fn sync_sample_wall_times(
    data: &[u8],
    chunk_wall_epoch_ms: f64,
    cached_timescale: Option<u32>,
) -> (Vec<SyncSampleWall>, Option<u32>) {
    let mut timescale = cached_timescale.unwrap_or(90_000);
    let mut moov_range: Option<std::ops::Range<usize>> = None;
    walk_boxes(data, |typ, r| {
        if typ == *b"moov" {
            moov_range = Some(r);
        }
    });
    if let Some(r) = moov_range.clone() {
        if let Some(ts) = timescale_from_moov(&data[r]) {
            timescale = ts;
        }
    }

    let mut moof_range: Option<std::ops::Range<usize>> = None;
    walk_boxes(data, |typ, r| {
        if typ == *b"moof" {
            moof_range = Some(r);
        }
    });
    let Some(moof) = moof_range else {
        return (Vec::new(), Some(timescale));
    };

    let moof = &data[moof.clone()];
    let mut tfdt_base: u64 = 0;
    let mut trun_range: Option<std::ops::Range<usize>> = None;
    walk_boxes(moof, |typ, r| {
        if typ == *b"traf" {
            let traf = &moof[r.clone()];
            walk_boxes(traf, |t2, r2| {
                if t2 == *b"tfdt" && traf.len() >= r2.end && r2.end >= r2.start + 12 {
                    let full = &traf[r2.start - 8..r2.end];
                    let ver = full[8];
                    if ver == 1 && full.len() >= 20 {
                        tfdt_base = read_u64_be(full, 12).unwrap_or(0);
                    } else if full.len() >= 16 {
                        tfdt_base = read_u32_be(full, 12).unwrap_or(0) as u64;
                    }
                }
                if t2 == *b"trun" {
                    trun_range = Some(r2);
                }
            });
        }
    });
    let Some(trun_body) = trun_range else {
        return (Vec::new(), Some(timescale));
    };
    let trun = &moof[trun_body.clone()];
    if trun.len() < 12 {
        return (Vec::new(), Some(timescale));
    }
    let ver = trun[0];
    let flags = u32::from_be_bytes([0, trun[1], trun[2], trun[3]]);
    let sample_count = read_u32_be(trun, 4).unwrap_or(0) as usize;
    let mut o = 8usize;
    if ver == 1 {
        o += 8;
    } else {
        o += 4;
    }
    let data_offset_present = (flags & 0x000001) != 0;
    let first_sample_flags_present = (flags & 0x000004) != 0;
    let sample_duration_present = (flags & 0x000100) != 0;
    let sample_size_present = (flags & 0x000200) != 0;
    let sample_flags_present = (flags & 0x000400) != 0;
    let sample_composition_time_offsets_present = (flags & 0x000800) != 0;

    if data_offset_present {
        o += 4;
    }
    let mut first_flags = 0u32;
    if first_sample_flags_present && o + 4 <= trun.len() {
        first_flags = read_u32_be(trun, o).unwrap_or(0);
        o += 4;
    }

    let mut dts = tfdt_base;
    let mut out = Vec::new();
    for i in 0..sample_count {
        let mut dur = 0u32;
        if sample_duration_present {
            if o + 4 > trun.len() {
                break;
            }
            dur = read_u32_be(trun, o).unwrap_or(0);
            o += 4;
        }
        let mut sz = 0u32;
        if sample_size_present {
            if o + 4 > trun.len() {
                break;
            }
            sz = read_u32_be(trun, o).unwrap_or(0);
            o += 4;
        }
        let mut fl = first_flags;
        if i > 0 {
            fl = 0;
        }
        if sample_flags_present {
            if o + 4 > trun.len() {
                break;
            }
            fl = read_u32_be(trun, o).unwrap_or(0);
            o += 4;
        }
        if sample_composition_time_offsets_present {
            o += if ver == 1 { 4 } else { 4 };
        }

        let is_non_sync = (fl & 0x0001_0000) != 0;
        if !is_non_sync {
            let rel_ms = ((dts.saturating_sub(tfdt_base)) as f64) * 1000.0 / (timescale as f64);
            out.push(SyncSampleWall {
                wall_epoch_ms: chunk_wall_epoch_ms + rel_ms,
                sample_index_in_fragment: i as u32,
            });
        }
        dts = dts.saturating_add(u64::from(dur));
    }

    (out, Some(timescale))
}

/// Sample-level trim (full moof/mdat rebuild) — not implemented; use whole fragment from keyframe chunk.
pub fn trim_fragment_with_init(
    _fragment: &[u8],
    _init: &[u8],
    _from_sample: u32,
) -> Result<Vec<u8>, &'static str> {
    Err("sample-level trim not implemented")
}
