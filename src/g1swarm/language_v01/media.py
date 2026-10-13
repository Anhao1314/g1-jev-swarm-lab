"""New-run state playback only; never renders historical or synthetic captures."""
import importlib.util
from pathlib import Path
import time

from .demo_identity import read, sha, write, ROOT, HERE


def render_saved(directory: Path, source: dict, deadline: float) -> dict:
    directory = Path(directory).resolve()
    receipt = read(directory/'physical.json')
    if (receipt.get('kind') != 'NEW_MUJOCO_CAPTURE' or receipt.get('C_exec') != source['C_exec']
            or receipt.get('native_completed', 0) <= 0 or 'poses.npz' not in receipt.get('files', {})):
        raise PermissionError('NO_QUALIFIED_NEW_RUN_CAPTURE_FOR_MEDIA')
    for name in ('poses.npz', 'result.json'):
        if sha(directory/name) != receipt['files'].get(name):
            raise ValueError('NEW_CAPTURE_CONTENT_DRIFT:'+name)
    renderer = source['renderer']
    encoder = Path(renderer['exe']).resolve()
    if sha(encoder) != renderer['sha256']: raise ValueError('ENCODER_IDENTITY_DRIFT')
    model_rel = 'third_party/unitree_rl_gym/resources/robots/g1_description/scene.xml'
    model = (Path(source['asset_root'])/model_rel).resolve()
    if sha(model) != source['assets'][model_rel]: raise ValueError('RENDER_MODEL_IDENTITY_DRIFT')
    if time.perf_counter() >= deadline: raise TimeoutError('MEDIA_DEADLINE_EXCEEDED')
    protocol = read(HERE/'demo_protocol.json')
    if protocol['render_only']['width'] != 640 or protocol['render_only']['height'] != 360:
        raise ValueError('FROZEN_MEDIA_DIMENSIONS_MISMATCH')
    # Import lazily: module imports MuJoCo, but only forwards saved state.
    spec = importlib.util.spec_from_file_location('language_g1_new_capture_renderer', ROOT/'console/build_m2_replay.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.XML, module.ENCODER = model, encoder
    original = module.mujoco.mj_step
    def forbidden(*args, **kwargs): raise RuntimeError('RENDER_PHYSICS_STEP_FORBIDDEN')
    module.mujoco.mj_step = forbidden
    try: rendered = module.render(directory, directory/'video.mp4', width=640, height=360)
    finally: module.mujoco.mj_step = original
    if time.perf_counter() >= deadline: raise TimeoutError('MEDIA_DEADLINE_EXCEEDED_AFTER_RENDER')
    if (rendered.get('source_pose_sha256') != receipt['files']['poses.npz'] or
            rendered.get('mj_step_calls') != 0 or not rendered.get('passed')):
        raise ValueError('RENDER_RECEIPT_CONTENT_MISMATCH')
    media = {'kind':'NEW_RUN_STATE_PLAYBACK','request_id':receipt['request_id'],
             'C_exec':receipt['C_exec'],'preparation_sha256':receipt['preparation_sha256'],
             'executed_mission_sha256':receipt['executed_mission_sha256'],
             'protocol_sha256':sha(HERE/'demo_protocol.json'),'width':640,'height':360,
             'source_physical_sha256':sha(directory/'physical.json'),'source_result_sha256':sha(directory/'result.json'),
             'new_capture':True,'historical_fallback':False,'renderer':rendered,'file':'video.mp4'}
    write(directory/'media.json', media)
    return media
