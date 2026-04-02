//! Minimal fMP4 parsing for MediaRecorder chunks (strict assumptions).
//!
//! - One `moof` + one `mdat` per fragment after init, or `ftyp`+`moov` init segment.
//! - One `traf`/`trun` per `moof`; sync samples: `sample_is_non_sync` bit clear in `sample_flags`
//!   (ISO 14496-12: bit 16 of sample_flags = is_non_sync_sample).
//! - Timescale from `moov/mdhd` when present in the same buffer or from `cached_timescale`.
//! - Multi-track fragments: first chunk waits until a fragment starts on a video keyframe (drop
//!   whole fragments); single-track video can trim leading non-sync samples in one fragment.

fn read_u32_be(b: &[u8], i: usize) -> Option<u32> {
    b.get(i..i + 4)?.try_into().ok().map(u32::from_be_bytes)
}

fn read_u64_be(b: &[u8], i: usize) -> Option<u64> {
    b.get(i..i + 8)?.try_into().ok().map(u64::from_be_bytes)
}

fn read_i32_be(b: &[u8], i: usize) -> Option<i32> {
    b.get(i..i + 4)?.try_into().ok().map(i32::from_be_bytes)
}

fn fourcc(b: &[u8], i: usize) -> Option<[u8; 4]> {
    b.get(i..i + 4)?.try_into().ok()
}

/// Walk top-level boxes; `cb` receives (box_type, full box range including 8-byte header).
fn walk_boxes<F: FnMut([u8; 4], std::ops::Range<usize>)>(data: &[u8], mut cb: F) {
    let mut i = 0usize;
    while i + 8 <= data.len() {
        let sz = read_u32_be(data, i).unwrap_or(0) as usize;
        if sz == 0 {
            break;
        }
        if sz == 1 {
            // large size: skip for now (rare for our fragments)
            break;
        }
        if sz < 8 {
            break;
        }
        let end = i.saturating_add(sz).min(data.len());
        let typ = fourcc(data, i + 4).unwrap_or([0, 0, 0, 0]);
        cb(typ, i..end);
        i = end;
    }
}

/// Walk boxes inside `data` as payload (no outer header); `cb` gets (type, range of inner payload).
fn walk_inner_boxes<F: FnMut([u8; 4], std::ops::Range<usize>)>(data: &[u8], mut cb: F) {
    let mut i = 0usize;
    while i + 8 <= data.len() {
        let sz = read_u32_be(data, i).unwrap_or(0) as usize;
        if sz < 8 || sz > data.len().saturating_sub(i) {
            break;
        }
        let end = i + sz;
        let typ = fourcc(data, i + 4).unwrap_or([0, 0, 0, 0]);
        let inner = (i + 8)..end;
        cb(typ, inner);
        i = end;
    }
}

/// Extract concatenation of `ftyp` and `moov` boxes from a buffer (if present).
pub fn extract_ftyp_moov(data: &[u8]) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    walk_boxes(data, |typ, r| {
        if typ == *b"ftyp" || typ == *b"moov" {
            out.extend_from_slice(&data[r.start..r.end]);
        }
    });
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

fn find_top_level_box_range(data: &[u8], want: &[u8; 4]) -> Option<std::ops::Range<usize>> {
    let mut found = None;
    walk_boxes(data, |typ, r| {
        if typ == *want {
            found = Some(r);
        }
    });
    found
}

/// Read `timescale` from `moov/trak/mdia/mdhd` (first track only).
pub fn timescale_from_moov(moov_payload: &[u8]) -> Option<u32> {
    let mut found = None;
    walk_inner_boxes(moov_payload, |typ, r| {
        if typ == *b"trak" {
            let trak = &moov_payload[r.clone()];
            walk_inner_boxes(trak, |t2, r2| {
                if t2 == *b"mdia" {
                    let mdia = &trak[r2.clone()];
                    walk_inner_boxes(mdia, |t3, r3| {
                        if t3 == *b"mdhd" && r3.end >= r3.start + 20 {
                            let off = r3.start + 12;
                            if let Some(ts) = read_u32_be(mdia, off) {
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

/// Video `trak` id (`tkhd.track_id`) for the track whose `hdlr` is `vide`.
fn video_track_id_from_moov_payload(moov_payload: &[u8]) -> Option<u32> {
    let mut result: Option<u32> = None;
    walk_inner_boxes(moov_payload, |typ, r| {
        if typ != *b"trak" {
            return;
        }
        let trak = &moov_payload[r.clone()];
        let mut is_video = false;
        walk_inner_boxes(trak, |t2, r2| {
            if t2 == *b"mdia" {
                let mdia = &trak[r2.clone()];
                walk_inner_boxes(mdia, |t3, r3| {
                    if t3 == *b"hdlr" && r3.end >= r3.start + 12 {
                        let h = &mdia[r3.start..r3.end];
                        if h.len() >= 12 && &h[8..12] == b"vide" {
                            is_video = true;
                        }
                    }
                });
            }
        });
        if !is_video {
            return;
        }
        walk_inner_boxes(trak, |t2, r2| {
            if t2 == *b"tkhd" {
                let h = &trak[r2.clone()];
                if h.len() >= 20 {
                    if let Some(id) = read_u32_be(h, 12) {
                        result = Some(id);
                    }
                }
            }
        });
    });
    result
}

/// Video track id from init segment (`ftyp`+`moov` bytes).
pub fn video_track_id_from_init(init: &[u8]) -> Option<u32> {
    let moov_r = find_top_level_box_range(init, b"moov")?;
    let moov_payload = init.get(moov_r.start + 8..moov_r.end)?;
    video_track_id_from_moov_payload(moov_payload)
}

fn count_trafs_in_moof(moof_payload: &[u8]) -> usize {
    let mut n = 0;
    walk_inner_boxes(moof_payload, |typ, _| {
        if typ == *b"traf" {
            n += 1;
        }
    });
    n
}

fn tfhd_track_id(tfhd_inner: &[u8]) -> Option<u32> {
    // tfhd: version(1) + flags(3) + track_id(4) at offset 4 from inner payload
    if tfhd_inner.len() >= 8 {
        return read_u32_be(tfhd_inner, 4);
    }
    None
}

/// First video sync sample index in the first `moof` of `data` (fragment or full file).
pub fn first_video_sync_sample_index(data: &[u8], video_track_id: u32) -> Option<u32> {
    let moof_r = find_top_level_box_range(data, b"moof")?;
    let moof_payload = data.get(moof_r.start + 8..moof_r.end)?;
    let mut result: Option<u32> = None;
    walk_inner_boxes(moof_payload, |typ, r| {
        if typ != *b"traf" {
            return;
        }
        let traf = &moof_payload[r.clone()];
        let mut tid = None;
        let mut trun_slice: Option<&[u8]> = None;
        walk_inner_boxes(traf, |t2, r2| {
            if t2 == *b"tfhd" {
                let inner = &traf[r2.clone()];
                tid = tfhd_track_id(inner);
            }
            if t2 == *b"trun" {
                trun_slice = Some(&traf[r2.clone()]);
            }
        });
        if tid != Some(video_track_id) {
            return;
        }
        if let Some(body) = trun_slice {
            result = parse_trun_first_sync_index(body);
        }
    });
    result
}

fn parse_trun_first_sync_index(trun: &[u8]) -> Option<u32> {
    if trun.len() < 12 {
        return None;
    }
    let ver = trun[0];
    let flags = u32::from_be_bytes([0, trun[1], trun[2], trun[3]]);
    let sample_count = read_u32_be(trun, 4)? as usize;
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
        first_flags = read_u32_be(trun, o)?;
        o += 4;
    }

    for i in 0..sample_count {
        if sample_duration_present {
            o += 4;
        }
        if sample_size_present {
            o += 4;
        }
        let mut fl = if i == 0 { first_flags } else { 0 };
        if sample_flags_present && o + 4 <= trun.len() {
            fl = read_u32_be(trun, o)?;
            o += 4;
        }
        if sample_composition_time_offsets_present {
            o += if ver == 1 { 4 } else { 4 };
        }
        let is_non_sync = (fl & 0x0001_0000) != 0;
        if !is_non_sync {
            return Some(i as u32);
        }
    }
    None
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
        if let Some(ts) = timescale_from_moov(&data[r.start + 8..r.end]) {
            timescale = ts;
        }
    }

    let mut moof_range: Option<std::ops::Range<usize>> = None;
    walk_boxes(data, |typ, r| {
        if typ == *b"moof" {
            moof_range = Some(r);
        }
    });
    let Some(moof_r) = moof_range else {
        return (Vec::new(), Some(timescale));
    };

    let moof = &data[moof_r.start + 8..moof_r.end];
    let mut tfdt_base: u64 = 0;
    let mut trun_range: Option<std::ops::Range<usize>> = None;
    walk_inner_boxes(moof, |typ, r| {
        if typ == *b"traf" {
            let traf = &moof[r.clone()];
            walk_inner_boxes(traf, |t2, r2| {
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
        if sample_size_present {
            if o + 4 > trun.len() {
                break;
            }
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
            o += 4;
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

// --- Single-traf trim: rebuild moof + slice mdat ---

#[derive(Clone)]
struct ParsedTrunSample {
    duration: Option<u32>,
    size: u32,
    flags: u32,
    composition_offset: Option<i32>,
}

fn parse_trun_samples(trun: &[u8]) -> Option<(u8, u32, i32, Vec<ParsedTrunSample>)> {
    if trun.len() < 12 {
        return None;
    }
    let ver = trun[0];
    let flags = u32::from_be_bytes([0, trun[1], trun[2], trun[3]]);
    let sample_count = read_u32_be(trun, 4)? as usize;
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

    let mut data_offset = 0i32;
    if data_offset_present {
        data_offset = read_i32_be(trun, o)?;
        o += 4;
    }
    let mut first_flags = 0u32;
    if first_sample_flags_present && o + 4 <= trun.len() {
        first_flags = read_u32_be(trun, o)?;
        o += 4;
    }

    let mut samples = Vec::with_capacity(sample_count);
    for i in 0..sample_count {
        let mut dur = None;
        if sample_duration_present {
            dur = Some(read_u32_be(trun, o)?);
            o += 4;
        }
        let mut sz = 0u32;
        if sample_size_present {
            sz = read_u32_be(trun, o)?;
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
            fl = read_u32_be(trun, o)?;
            o += 4;
        }
        let mut cto = None;
        if sample_composition_time_offsets_present {
            if o + 4 > trun.len() {
                break;
            }
            cto = Some(read_i32_be(trun, o)?);
            o += 4;
        }
        samples.push(ParsedTrunSample {
            duration: dur,
            size: sz,
            flags: fl,
            composition_offset: cto,
        });
    }
    Some((ver, flags, data_offset, samples))
}

/// Trim single-traf `moof`/`mdat` so the first kept sample is `from_sample` (must be a sync sample).
fn trim_single_traf_fragment(fragment: &[u8], init: &[u8], from_sample: u32) -> Result<Vec<u8>, &'static str> {
    let moof_r = find_top_level_box_range(fragment, b"moof").ok_or("no moof")?;
    let mdat_r = find_top_level_box_range(fragment, b"mdat").ok_or("no mdat")?;
    if count_trafs_in_moof(&fragment[moof_r.start + 8..moof_r.end]) != 1 {
        return Err("expected single traf");
    }

    let moof_start = moof_r.start;
    let moof_payload = &fragment[moof_r.start + 8..moof_r.end];
    let mut traf_r: Option<std::ops::Range<usize>> = None;
    walk_inner_boxes(moof_payload, |typ, r| {
        if typ == *b"traf" {
            traf_r = Some(r);
        }
    });
    let traf_r = traf_r.ok_or("no traf")?;
    let traf = &moof_payload[traf_r.clone()];
    let mut tfdt_r: Option<std::ops::Range<usize>> = None;
    let mut trun_r: Option<std::ops::Range<usize>> = None;
    walk_inner_boxes(traf, |typ, r| {
        if typ == *b"tfdt" {
            tfdt_r = Some(r.clone());
        }
        if typ == *b"trun" {
            trun_r = Some(r.clone());
        }
    });
    let trun_range = trun_r.ok_or("no trun")?;
    let trun_full = traf
        .get(trun_range.start - 8..trun_range.end)
        .ok_or("trun range")?;
    let trun_inner = &trun_full[8..];
    let (ver, flags, data_offset, samples) = parse_trun_samples(trun_inner).ok_or("parse trun")?;
    if from_sample as usize >= samples.len() {
        return Err("from_sample out of range");
    }

    let tfdt_range = tfdt_r.ok_or("no tfdt")?;
    let tfdt_full = traf
        .get(tfdt_range.start - 8..tfdt_range.end)
        .ok_or("tfdt range")?;
    let tfdt_inner = &tfdt_full[8..];
    let mut tfdt_base: u64 = 0;
    let tver = tfdt_inner[0];
    if tver == 1 && tfdt_inner.len() >= 12 {
        tfdt_base = read_u64_be(tfdt_inner, 4).unwrap_or(0);
    } else if tfdt_inner.len() >= 8 {
        tfdt_base = read_u32_be(tfdt_inner, 4).unwrap_or(0) as u64;
    }

    let mut dts = tfdt_base;
    for s in samples.iter().take(from_sample as usize) {
        dts = dts.saturating_add(u64::from(s.duration.unwrap_or(0)));
    }
    let new_tfdt_base = dts;

    let moof_abs = moof_start;
    let first_sample_pos = moof_abs as i64 + i64::from(data_offset);
    let mdat_payload_start = mdat_r.start + 8;
    let mut sample_pos = first_sample_pos;
    for s in samples.iter().take(from_sample as usize) {
        sample_pos += i64::from(s.size);
    }
    if sample_pos < mdat_payload_start as i64 {
        return Err("sample offset before mdat");
    }
    let new_mdat_payload = fragment.get(sample_pos as usize..mdat_r.end).ok_or("mdat slice")?;

    let kept: Vec<ParsedTrunSample> = samples[from_sample as usize..].to_vec();
    if kept.is_empty() {
        return Err("no samples after trim");
    }

    let new_first_sample_pos = sample_pos as usize;
    let new_data_offset = (new_first_sample_pos as i64 - moof_start as i64) as i32;

    let new_trun_body = rebuild_trun_bytes(trun_inner, ver, flags, &kept, new_data_offset)?;
    let new_tfdt_bytes = rebuild_tfdt_bytes(tfdt_inner, new_tfdt_base)?;

    let mut new_moof_payload = Vec::new();
    walk_inner_boxes(moof_payload, |typ, r| {
        if typ == *b"mfhd" {
            new_moof_payload.extend_from_slice(&moof_payload[r.start - 8..r.end]);
        }
    });
    let mut new_traf = Vec::new();
    walk_inner_boxes(traf, |typ, r| {
        if typ == *b"tfhd" {
            new_traf.extend_from_slice(&traf[r.start - 8..r.end]);
        }
    });
    new_traf.extend_from_slice(&new_tfdt_bytes);
    new_traf.extend_from_slice(&new_trun_body);

    let traf_box = wrap_box(b"traf", &new_traf);
    new_moof_payload.extend_from_slice(&traf_box);
    let new_moof = wrap_box(b"moof", &new_moof_payload);

    let new_mdat = wrap_box(b"mdat", new_mdat_payload);

    let mut out = Vec::new();
    out.extend_from_slice(init);
    out.extend_from_slice(&new_moof);
    out.extend_from_slice(&new_mdat);
    Ok(out)
}

fn wrap_box(fourcc: &[u8; 4], inner: &[u8]) -> Vec<u8> {
    let sz = (inner.len() + 8) as u32;
    let mut v = Vec::with_capacity(inner.len() + 8);
    v.extend_from_slice(&sz.to_be_bytes());
    v.extend_from_slice(fourcc);
    v.extend_from_slice(inner);
    v
}

fn rebuild_tfdt_bytes(tfdt_inner: &[u8], new_base: u64) -> Result<Vec<u8>, &'static str> {
    let ver = tfdt_inner[0];
    let flags = u32::from_be_bytes([0, tfdt_inner[1], tfdt_inner[2], tfdt_inner[3]]);
    let mut inner = Vec::new();
    inner.push(ver);
    inner.extend_from_slice(&flags.to_be_bytes()[1..4]);
    if ver == 1 {
        inner.extend_from_slice(&new_base.to_be_bytes());
    } else {
        inner.extend_from_slice(&(new_base as u32).to_be_bytes());
    }
    Ok(wrap_box(b"tfdt", &inner))
}

fn rebuild_trun_bytes(
    old_trun_inner: &[u8],
    ver: u8,
    flags: u32,
    samples: &[ParsedTrunSample],
    data_offset: i32,
) -> Result<Vec<u8>, &'static str> {
    let _ = old_trun_inner;
    let mut body = Vec::new();
    body.push(ver);
    body.extend_from_slice(&flags.to_be_bytes()[1..4]);
    body.extend_from_slice(&(samples.len() as u32).to_be_bytes());
    if (flags & 0x000001) != 0 {
        body.extend_from_slice(&data_offset.to_be_bytes());
    }
    let first_sample_flags_present = (flags & 0x000004) != 0;
    if first_sample_flags_present {
        body.extend_from_slice(&samples[0].flags.to_be_bytes());
    }
    let sample_duration_present = (flags & 0x000100) != 0;
    let sample_size_present = (flags & 0x000200) != 0;
    let sample_flags_present = (flags & 0x000400) != 0;
    let sample_composition_time_offsets_present = (flags & 0x000800) != 0;

    for (i, s) in samples.iter().enumerate() {
        if sample_duration_present {
            body.extend_from_slice(&s.duration.ok_or("duration")?.to_be_bytes());
        }
        if sample_size_present {
            body.extend_from_slice(&s.size.to_be_bytes());
        }
        if sample_flags_present {
            if i == 0 && first_sample_flags_present {
                // already wrote first flags
            } else if i > 0 {
                body.extend_from_slice(&s.flags.to_be_bytes());
            } else if i == 0 && !first_sample_flags_present {
                body.extend_from_slice(&s.flags.to_be_bytes());
            }
        }
        if sample_composition_time_offsets_present {
            body.extend_from_slice(&s.composition_offset.unwrap_or(0).to_be_bytes());
        }
    }
    Ok(wrap_box(b"trun", &body))
}

/// Drop leading samples from the first `moof`/`mdat` using `init` (`ftyp`+`moov`); single-traf only.
pub fn trim_fragment_with_init(
    fragment: &[u8],
    init: &[u8],
    from_sample: u32,
) -> Result<Vec<u8>, &'static str> {
    trim_single_traf_fragment(fragment, init, from_sample)
}

// --- Session first chunk: init + keyframe at start ---

/// Mutable state while the first chunk of a recording session is not yet finalized.
#[derive(Default, Clone)]
pub struct SessionFirstChunkState {
    /// `session_id` this state applies to; reset `pending_init` when it changes.
    active_session: Option<String>,
    /// `ftyp`+`moov` retained when discarding a non-keyframe-leading fragment (multi-track).
    pub pending_init: Option<Vec<u8>>,
    /// After the first chunk is emitted for `active_session`, pass blobs through unchanged.
    pub first_chunk_done: bool,
}

impl SessionFirstChunkState {
    pub fn sync_session(&mut self, session_id: &str) {
        if self.active_session.as_deref() != Some(session_id) {
            self.active_session = Some(session_id.to_string());
            self.pending_init = None;
            self.first_chunk_done = false;
        }
    }
}

#[derive(Debug)]
pub enum FirstChunkOutcome {
    /// Enqueue this byte sequence as the chunk blob.
    Emit(Vec<u8>),
    /// Fragment consumed; do not enqueue (waiting for a keyframe-leading fragment).
    Skip,
}

/// Normalize the first chunk of a session: always includes `ftyp`+`moov`, and the first video
/// sample is a sync sample. Multi-track: may skip whole fragments until one starts on a keyframe.
pub fn session_first_chunk(
    bytes: &[u8],
    init_cache: Option<&[u8]>,
    state: &mut SessionFirstChunkState,
) -> FirstChunkOutcome {
    if state.first_chunk_done {
        return FirstChunkOutcome::Emit(bytes.to_vec());
    }

    let extracted = extract_ftyp_moov(bytes);
    let init_opt = extracted
        .as_deref()
        .or(init_cache)
        .or(state.pending_init.as_deref());

    let Some(init) = init_opt else {
        return FirstChunkOutcome::Skip;
    };
    let Some(vid) = video_track_id_from_init(init) else {
        return FirstChunkOutcome::Skip;
    };

    let combined: Vec<u8> = if extracted.is_some() {
        bytes.to_vec()
    } else {
        let mut c = match state.pending_init.clone() {
            Some(p) => p,
            None => return FirstChunkOutcome::Skip,
        };
        c.extend_from_slice(bytes);
        c
    };

    let sync_idx = first_video_sync_sample_index(&combined, vid);
    let moof_range = find_top_level_box_range(&combined, b"moof");

    if sync_idx.is_none() || moof_range.is_none() {
        if extracted.is_some() {
            state.pending_init = extracted.clone();
        }
        return FirstChunkOutcome::Skip;
    }
    let sync_idx = sync_idx.unwrap();
    let moof_range = moof_range.unwrap();
    let moof_payload = &combined[moof_range.start + 8..moof_range.end];
    let ntraf = count_trafs_in_moof(moof_payload);

    if sync_idx == 0 {
        let out = if extracted.is_none() {
            let mut v = match state.pending_init.take() {
                Some(p) => p,
                None => return FirstChunkOutcome::Skip,
            };
            v.extend_from_slice(bytes);
            v
        } else {
            bytes.to_vec()
        };
        state.first_chunk_done = true;
        state.pending_init = None;
        return FirstChunkOutcome::Emit(out);
    }

    // sync_idx > 0: need trim or skip
    if ntraf == 1 {
        match trim_single_traf_fragment(&combined, init, sync_idx) {
            Ok(out) => {
                state.first_chunk_done = true;
                state.pending_init = None;
                return FirstChunkOutcome::Emit(out);
            }
            Err(_) => {
                if extracted.is_some() {
                    state.pending_init = extracted.clone();
                }
                return FirstChunkOutcome::Skip;
            }
        }
    }

    // Multi-track: keep init, drop this fragment's media; wait for a moof that starts on IDR.
    if extracted.is_some() {
        state.pending_init = extracted;
    }
    FirstChunkOutcome::Skip
}

