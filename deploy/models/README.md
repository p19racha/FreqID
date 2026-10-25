# FreqID Models Directory

This directory stores offline-trained neural network checkpoints mounted into `freqid-server` at runtime.

## Required Model Checkpoint

The server expects the PartialFace ONNX feature extractor:
- **Default Filename**: `partialface_ir_18.onnx`
- **Mounted Path inside Container**: `/app/models/partialface_ir_18.onnx`

## Provisioning

To copy the locally trained or exported ONNX checkpoint:
```bash
cp research/outputs/checkpoints/partialface_ir_18.onnx deploy/models/
```
Or symlink it:
```bash
ln -s ../../research/outputs/checkpoints/partialface_ir_18.onnx deploy/models/partialface_ir_18.onnx
```

## Security Notice

Model checkpoints are strictly excluded from source control by `.gitignore` to maintain repository safety and prevent accidental redistribution of proprietary weights.
