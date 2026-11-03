"""One source-pixel point -> one validated SAM mask, without changing the guide."""
import asyncio
import base64
import math
import os
import re
import time

import requests
from meta_sam_parser import (
    FramePrompt, PromptObject, PromptPoint, SegmentationBoxRecord, SegmentationMaskRecord,
    build_object_prompt, decode_mask_to_raster, decode_mask_to_svg_path,
    image_segmentation_format, parse_responses_stream,
)

from .images import validate_box
from .vision import VisionError

MAX_WIRE_BYTES = 4 * 1024 * 1024
MAX_PATH_LENGTH = 200000


def pixel_point(point, width, height):
    return min(width - 1, point['x'] * width // 1000), min(height - 1, point['y'] * height // 1000)


def validate_selection(value, metadata, point):
    """The UI receives path data only, never arbitrary SVG markup or URLs."""
    try:
        if value['status'] == 'not_found':
            return {'status': 'not_found', 'point': dict(point)}
        if value['status'] != 'selected' or value['point'] != point:
            raise ValueError('selection identity')
        width, height = metadata['width'], metadata['height']
        if value['photo_width'] != width or value['photo_height'] != height:
            raise ValueError('source size')
        validate_box(value['box'])
        bounds = value['mask_bounds']
        if len(bounds) != 4 or any(type(n) is not int for n in bounds):
            raise ValueError('mask bounds')
        left, top, right, bottom = bounds
        x, y = pixel_point(point, width, height)
        if not (0 <= left <= x < right <= width and 0 <= top <= y < bottom <= height):
            raise ValueError('point outside mask bounds')
        expected_box = [math.floor(left * 1000 / width), math.floor(top * 1000 / height),
                        math.ceil(right * 1000 / width), math.ceil(bottom * 1000 / height)]
        if value['box'] != expected_box:
            raise ValueError('mask/box mismatch')
        path = value['mask_path']
        if not isinstance(path, str) or not 0 < len(path) <= MAX_PATH_LENGTH or not re.fullmatch(r'[MLZmlz0-9eE,.+\s-]+', path):
            raise ValueError('invalid path')
        return {key: value[key] for key in ('status', 'point', 'box', 'mask_bounds', 'mask_path', 'photo_width', 'photo_height')}
    except (KeyError, TypeError, ValueError, OverflowError):
        raise VisionError('invalid_selection', '물체의 윤곽을 확인하지 못했습니다. 물체 안쪽을 다시 선택해 주세요.') from None


async def _parse_events(events):
    async def source():
        for event in events:
            yield event
    return await parse_responses_stream(source(), image_segmentation_format()).final_result()


def segment_object(data, metadata, point):
    key = os.getenv('MODEL_API_KEY', '').strip()
    if not key:
        raise VisionError('missing_key', 'SAM API 설정을 확인해 주세요.')
    if os.getenv('META_API_BASE_URL', 'https://api.meta.ai/v1').rstrip('/') != 'https://api.meta.ai/v1':
        raise VisionError('configuration', 'Meta API 주소 설정을 확인해 주세요.')
    width, height = metadata['width'], metadata['height']
    x, y = pixel_point(point, width, height)
    prompt = build_object_prompt(size=(width, height), objects=[PromptObject(id=1, prompts=[FramePrompt(points=[PromptPoint(x, y)])])])
    payload = {'model': 'sam-3.1', 'input': [{'type': 'message', 'role': 'user', 'content': [
        {'type': 'input_text', 'text': prompt},
        {'type': 'input_image', 'image_url': 'data:image/jpeg;base64,' + base64.b64encode(data).decode()},
    ]}], 'stream': True, 'metadata': {'mask_encoding': 'one_bit'}}
    started = time.monotonic()
    events, wire_bytes = [], 0
    try:
        with requests.post('https://api.meta.ai/v1/responses', headers={'Authorization': 'Bearer ' + key, 'Accept': 'text/event-stream'},
                           json=payload, stream=True, timeout=(10, 90), allow_redirects=False) as response:
            if response.status_code != 200:
                code = {401: 'authentication', 402: 'billing', 403: 'permission', 429: 'rate_limit'}.get(response.status_code, 'upstream')
                raise VisionError(code, '지금은 물체의 윤곽을 찾을 수 없습니다. 잠시 뒤 다시 시도해 주세요.')
            for line in response.iter_lines():
                wire_bytes += len(line)
                if wire_bytes > MAX_WIRE_BYTES or time.monotonic() - started > 90:
                    raise VisionError('timeout', '윤곽 확인이 오래 걸립니다. 기존 사진과 설명은 계속 볼 수 있어요.')
                if line.startswith(b'data: ') and line[6:] != b'[DONE]':
                    import json
                    events.append(json.loads(line[6:]))
    except requests.Timeout:
        raise VisionError('timeout', '윤곽 확인이 오래 걸립니다. 물체 안쪽을 다시 선택해 주세요.') from None
    except requests.RequestException:
        raise VisionError('connection', '윤곽을 찾는 서비스에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.') from None
    except (ValueError, TypeError):
        raise VisionError('invalid_selection', '윤곽 응답을 읽지 못했습니다. 다시 선택해 주세요.') from None
    try:
        result = asyncio.run(_parse_events(events))
        if result.outcome.status != 'completed':
            raise ValueError('incomplete')
        boxes = [r for r in result.records if isinstance(r, SegmentationBoxRecord)]
        masks = [r for r in result.records if isinstance(r, SegmentationMaskRecord)]
        metrics = {'model': 'sam-3.1', 'elapsed_seconds': round(time.monotonic() - started, 3)}
        completed = next((e.get('response', {}) for e in reversed(events) if e.get('type') == 'response.completed'), {})
        metrics['usage'] = completed.get('usage', {})
        if not boxes and not masks:
            return {'status': 'not_found', 'point': point}, metrics
        if len(boxes) != 1 or len(masks) != 1 or boxes[0].object_id != '1' or masks[0].object_id != '1':
            raise ValueError('not one object')
        mask = masks[0]
        bounds = [mask.bounds.left, mask.bounds.top, mask.bounds.right, mask.bounds.bottom]
        if any(int(n) != n for n in bounds):
            raise ValueError('fractional bounds')
        left, top, right, bottom = bounds = [int(n) for n in bounds]
        if not (0 <= left <= x < right <= width and 0 <= top <= y < bottom <= height):
            return {'status': 'not_found', 'point': point}, metrics
        if mask.mask.width != right - left or mask.mask.height != bottom - top:
            raise ValueError('mask size')
        raster = decode_mask_to_raster(mask.mask)
        if not raster[(y - top) * mask.mask.width + (x - left)]:
            return {'status': 'not_found', 'point': point}, metrics
        selection = {'status': 'selected', 'point': point,
                     'box': [math.floor(left * 1000 / width), math.floor(top * 1000 / height), math.ceil(right * 1000 / width), math.ceil(bottom * 1000 / height)],
                     'mask_bounds': bounds, 'mask_path': decode_mask_to_svg_path(mask.mask), 'photo_width': width, 'photo_height': height}
        return validate_selection(selection, metadata, point), metrics
    except VisionError:
        raise
    except Exception:
        # Parser errors must never leak upstream bodies, request images or credentials.
        raise VisionError('invalid_selection', '윤곽을 하나의 물체로 확인하지 못했습니다. 물체 안쪽을 다시 선택해 주세요.') from None
