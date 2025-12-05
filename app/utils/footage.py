import json
from models import Match, Point, db
from os import path
import subprocess 
from itertools import groupby
from datetime import datetime, timezone

def finalize_recording_worker(logger, tournament_url, field_name, session_id, match_id, camera_name, chunk_dir):
    # Check if first chunk exists
    first_chunk_path = path.join(chunk_dir, 'chunk_000000.webm')
    if not path.exists(first_chunk_path):
        return
    
    with open(path.join(chunk_dir, 'chunks_meta.json'), 'r') as f:
        consecutive = list(
            map(
                lambda x: sorted(
                    x[1], 
                    key=lambda c: c['chunk_start_timestamp']
                ),
                groupby(
                    sorted(
                        json.load(f)
                            .values(),
                        key=lambda x: x['point_id']
                    ),
                    key=lambda x: x['point_id']
                )
            )
        )
    
    # concatenate the chunks from each point into a single playable video
    for idx, chunks in enumerate(consecutive):
        print(f"chunk {idx} has length {len(chunks)}")
        with open(path.join(chunk_dir, f"{chunks[0]['point_id']}.webm"), 'ab') as c:
            for chunk in chunks:
                with open(path.join(chunk_dir, chunk['filename']), 'rb') as f:
                    c.write(f.read())
        # Fix timestamps - works for both WebM and MP4 (even with .webm extension)
        subprocess.run(['ffmpeg',
            '-i', path.join(chunk_dir, f"{chunks[0]['point_id']}.webm"),
            '-map', '0',
            '-c', 'copy',
            '-loglevel', 'error',
            '-y',
            path.join(chunk_dir, f"{chunks[0]['point_id']}_fixedstamps.webm")
        ])
        print('Subprocess call complete!')

    pts = Point.query.filter_by(match=match_id).order_by(Point.stamp.asc()).all()
    print(f"len(pts) is {len(pts)}")
    point_table = { chunks[0]['point_id']: (chunks[0]['chunk_start_timestamp'], len(chunks)) for chunks in consecutive }
    in_video_times = [[None, 0.01]]
    with open(path.join(chunk_dir, 'clips.txt'), 'w') as clips:
        for pt in pts:
            output_filename = path.join(chunk_dir, f'{pt.uuid}_clipped.webm')
            if pt.uuid not in point_table:
                print(f'POINT {pt.uuid} NOT FOUND IN POINT TABLE!')
                print(f'point_table={point_table}')
                continue
            start_stamp, end_stamp = \
                pt.stamp.replace(tzinfo=timezone.utc).timestamp() - point_table[pt.uuid][0]/1000 - 3, \
                pt.end_stamp.replace(tzinfo=timezone.utc).timestamp() - point_table[pt.uuid][0]/1000 + 3
            if start_stamp < -3:
                print(f'what the fuck?? point starts before recording? start: {start_stamp}+3, end: {end_stamp}-3, point table: {point_table}')
                # in_video_times.append([None, in_video_times[-1][1]])
                continue
            start_stamp = max(0, start_stamp)
            in_video_times[-1][0] = pt.uuid
            if (end_stamp > point_table[pt.uuid][1]*2) or (start_stamp > end_stamp):
                # something's wrong; we don't have all the 
                # footage from this point. so just set this
                # point's length to zero and skip adding
                # the footage.
                print(f'somethings wrong! start: {start_stamp}, end: {end_stamp} (duration {end_stamp-start_stamp}), point table entry: {point_table[pt.uuid]}')
                print(f'point_table={point_table}')
                in_video_times.append([None, in_video_times[-1][1]])
                continue
            in_video_times.append([None, in_video_times[-1][1] + end_stamp-start_stamp])
            print(f"RUNNING FFMPEG FOR POINT {pt.uuid} !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            
            # Clip the video - works for both WebM and MP4 input (even with .webm extension)
            # Always output as WebM/VP9 for consistency, so concatenation works smoothly
            input_file = path.join(chunk_dir, f'{pt.uuid}_fixedstamps.webm')
            
            # Probe the input file to detect codec
            probe_result = subprocess.run(['ffprobe',
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=codec_name',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                input_file
            ], capture_output=True, text=True)
            
            codec_name = probe_result.stdout.strip() if probe_result.returncode == 0 else ''
            
            # Always output as WebM/VP9 format for consistency
            # If input is already VP9, we can copy; otherwise re-encode
            if codec_name == 'vp9':
                # Input is already VP9, can copy video codec
                subprocess.run(['ffmpeg',
                    '-ss', str(start_stamp),
                    '-to', str(end_stamp),
                    '-i', input_file,
                    '-c:v', 'copy',  # Copy VP9 video
                    '-c:a', 'copy',  # Copy audio
                    '-loglevel', 'error',
                    '-y',
                    output_filename
                ])
            else:
                # Input is MP4/H.264 or VP8, re-encode to VP9/WebM
                subprocess.run(['ffmpeg',
                    '-ss', str(start_stamp),
                    '-to', str(end_stamp),
                    '-i', input_file,
                    '-c:v', 'libvpx-vp9', 
                    '-crf', '16',
                    '-b:v', '0',
                    '-c:a', 'libopus',  # Use opus for WebM (works with both MP4 and WebM input)
                    '-loglevel', 'error',
                    '-y',
                    output_filename
                ])
            print(f"file {output_filename}", file=clips)

    # Concatenate all clips into final video
    # All clips should now be WebM/VP9 format (from clipping step above)
    # So we can use copy for fast concatenation
    subprocess.run(['ffmpeg', 
        '-f', 'concat', 
        '-safe', '0', 
        '-i', path.join(chunk_dir, 'clips.txt'),
        '-c', 'copy',  # Copy works since all clips are now WebM/VP9
        '-map', '0', 
        '-y', 
        path.join(chunk_dir, 'final_video.webm')
    ])
    

    with open(path.join(chunk_dir, 'metadata.json'), 'r') as f:
        metadata = json.load(f)

    # for debug visibility
    metadata['point_timestamps'] = [i[1] for i in in_video_times]
    with open(path.join(chunk_dir, 'metadata.json'), 'w') as f:
        json.dump(metadata, f)

    print(f"match id: {match_id}")
    match = Match.query.filter_by(uuid=match_id).first()
    stream_starts = json.loads(match.camera_stream_starts) if match.camera_stream_starts else dict()
    print(f"STREAM STARTS: {stream_starts}")
    stream_starts[camera_name] = {
        'video_path': path.join(
            'uploads/videos',
            tournament_url,
            field_name,
            session_id,
            'final_video.webm'
        ),
        'point_timestamps': [i[1] for i in in_video_times],
        'type': 'recorded',
    }
    match.camera_stream_starts = json.dumps(stream_starts)
    db.session.commit()