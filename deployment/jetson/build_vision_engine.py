#!/usr/bin/env python3
"""Build a device-specific static FP16 engine on the Jetson, never on the Windows PC."""
import argparse,hashlib,json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('model',type=Path);args=parser.parse_args()
    import tensorrt as trt
    logger=trt.Logger(trt.Logger.WARNING);builder=trt.Builder(logger)
    network=builder.create_network(1<<int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    onnx=trt.OnnxParser(network,logger)
    if not onnx.parse(args.model.read_bytes()):raise RuntimeError('\n'.join(str(onnx.get_error(i)) for i in range(onnx.num_errors)))
    config=builder.create_builder_config()
    if hasattr(config,'set_memory_pool_limit'):config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE,256*1024*1024)
    else:config.max_workspace_size=256*1024*1024
    if builder.platform_has_fast_fp16:config.set_flag(trt.BuilderFlag.FP16)
    engine=builder.build_serialized_network(network,config)
    if engine is None:raise RuntimeError('TensorRT build failed')
    path=args.model.with_suffix('.engine');path.write_bytes(bytes(engine))
    meta=dict(onnx_sha256=hashlib.sha256(args.model.read_bytes()).hexdigest(),engine_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),tensorrt=trt.__version__,device_specific=True)
    path.with_suffix('.engine.json').write_text(json.dumps(meta,indent=2));print(path)

if __name__=='__main__':main()
