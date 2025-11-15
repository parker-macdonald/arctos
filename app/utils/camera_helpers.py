"""
Helper functions for camera/stream management.
"""
import re
import os
import requests
from datetime import datetime, timezone
import json


def extract_video_id(camera_url):
    """Extract YouTube video ID from various URL formats."""
    if not camera_url:
        return None
    
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([^&\n?#]+)',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, camera_url)
        if match:
            return match.group(1)
    return None


def get_stream_start_time(video_id):
    """Get YouTube live stream start time using YouTube Data API v3."""
    api_key = os.environ.get('YOUTUBE_API_KEY')
    if not api_key:
        return None
    
    try:
        url = f'https://www.googleapis.com/youtube/v3/videos'
        params = {
            'id': video_id,
            'part': 'liveStreamingDetails,snippet',
            'key': api_key
        }
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if not data.get('items'):
            return None
        
        video = data['items'][0]
        live_details = video.get('liveStreamingDetails', {})
        actual_start_time = live_details.get('actualStartTime')
        
        if actual_start_time:
            # Parse and ensure timezone-aware UTC
            start_dt = datetime.fromisoformat(actual_start_time.replace('Z', '+00:00'))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            return start_dt.isoformat().replace('+00:00', 'Z')
        
        return None
    except Exception as e:
        print(f"Error fetching stream start time for video {video_id}: {e}")
        return None


def parse_camera_urls(camera_field_value):
    """Parse camera field value - supports JSON array or single URL string."""
    if not camera_field_value:
        return []
    
    try:
        # Try parsing as JSON array
        cameras = json.loads(camera_field_value)
        if isinstance(cameras, list):
            return cameras
        elif isinstance(cameras, str):
            # Single URL as JSON string
            return [cameras]
    except (json.JSONDecodeError, TypeError):
        pass
    
    # Fallback: treat as single URL string
    return [camera_field_value] if camera_field_value.strip() else []


def get_all_camera_stream_starts(field):
    """Get stream start times for all cameras on a field.
    Returns dict mapping camera_index to stream start time (ISO format).
    """
    if not field or not field.camera:
        return {}
    
    camera_urls = parse_camera_urls(field.camera)
    stream_starts = {}
    
    for idx, camera_url in enumerate(camera_urls):
        video_id = extract_video_id(camera_url)
        if video_id:
            start_time = get_stream_start_time(video_id)
            if start_time:
                stream_starts[idx] = start_time
    
    return stream_starts


def calculate_stream_timestamp(point_stamp, stream_start_time):
    """Calculate timestamp in seconds from stream start.
    Uses the same calculation as the frontend calculateSeekTime function.
    
    Args:
        point_stamp: Point timestamp (datetime or ISO string)
        stream_start_time: Stream start time (ISO string)
    
    Returns:
        Timestamp in seconds from stream start, or None if calculation fails
    """
    if not point_stamp or not stream_start_time:
        return None
    
    try:
        # Parse point timestamp
        if isinstance(point_stamp, datetime):
            point_dt = point_stamp
            if point_dt.tzinfo is None:
                point_dt = point_dt.replace(tzinfo=timezone.utc)
        else:
            point_str = str(point_stamp)
            if not re.search(r'[zZ]|[\+\-]\d{2}:?\d{2}$', point_str):
                point_str = re.sub(r'\.\d+$', '', point_str) + 'Z'
            point_dt = datetime.fromisoformat(point_str.replace('Z', '+00:00'))
            if point_dt.tzinfo is None:
                point_dt = point_dt.replace(tzinfo=timezone.utc)
        
        # Parse stream start time
        stream_str = str(stream_start_time)
        if not re.search(r'[zZ]|[\+\-]\d{2}:?\d{2}$', stream_str):
            stream_str = re.sub(r'\.\d+$', '', stream_str) + 'Z'
        stream_dt = datetime.fromisoformat(stream_str.replace('Z', '+00:00'))
        if stream_dt.tzinfo is None:
            stream_dt = stream_dt.replace(tzinfo=timezone.utc)
        
        # Calculate difference in seconds
        diff = (point_dt - stream_dt).total_seconds()
        return diff if diff >= 0 else None
    except Exception as e:
        print(f"Error calculating stream timestamp: {e}")
        return None

