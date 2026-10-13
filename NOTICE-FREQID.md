# NOTICE: FreqID Derivative Work & Licensing Notice

## 1. Derivative Work Notice
This project, **FreqID**, is a derivative work built upon the open-source **TFace** framework developed by Tencent Youtu Lab.
- **Original Project:** Tencent/TFace (https://github.com/Tencent/TFace)
- **Original License:** Apache License, Version 2.0 (see [License.txt](License.txt))
- **Copyright:** Copyright (c) 2021 Tencent. All rights reserved.

The original Apache License, Version 2.0 terms apply to all code originating from Tencent/TFace.

---

## 2. PartialFace Research Citation
FreqID incorporates and adapts the principles and algorithms from the PartialFace research published at ICCV 2023:

```bibtex
@inproceedings{mi2023privacy,
  title={Privacy-Preserving Face Recognition Using Random Frequency Components},
  author={Mi, Yuxi and Huang, Yuge and Ji, Jiazhen and Zhao, Minyi and Wu, Jiaxiang and Xu, Xingkun and Ding, Shouhong and Zhou, Shuigeng},
  booktitle={Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV)},
  pages={19673--19684},
  year={2023}
}
```

---

## 3. Separate Licensing for Model Checkpoints and Datasets
Please note that machine learning model weights, pre-trained checkpoints, and training/benchmark datasets are distributed under separate terms:
- **Datasets**: Benchmark datasets such as BUPT-EqualizedFace, MS1Mv2, LFW, CFP-FP, AgeDB, CALFW, CPLFW, and IJB-B/C are owned by their respective institutions and authors. Many are restricted strictly to non-commercial research use. Users of FreqID are responsible for obtaining appropriate data access agreements and adhering to their respective licenses.
- **Pretrained Model Weights**: Checkpoint weights provided by Tencent or third parties carry separate licensing conditions. Verify individual weight licenses and restrictions prior to redistribution, commercial deployment, or hosted services.

---

## 4. `freqid-core` Source File Attributions

The `freqid-core` package ([`core/`](core/)) contains inference-only adaptations of Tencent/TFace modules under the Apache-2.0 License:

- **`core/src/freqid_core/transform.py`**:
  - Original source: [`recognition/tasks/partialface/utils.py`](recognition/tasks/partialface/utils.py)
  - Upstream base commit: `171ec14562098d5c416e6d1bb90cfaf53b4ae12e`
  - Copyright: Tencent Youtu Lab / PartialFace contributors (ICCV 2023)
  - License: Apache License, Version 2.0
- **`core/src/freqid_core/model.py`**:
  - Original source: [`recognition/torchkit/backbone/model_irse.py`](recognition/torchkit/backbone/model_irse.py) (and `ZhaoJ9014/face.evoLVe.PyTorch`)
  - Upstream base commit: `171ec14562098d5c416e6d1bb90cfaf53b4ae12e`
  - Copyright: Tencent Youtu Lab / face.evoLVe contributors
  - License: Apache License, Version 2.0
- **`core/src/freqid_core/payload.py`**, **`core/src/freqid_core/embedder.py`**, **`core/src/freqid_core/matching.py`**, **`core/src/freqid_core/export_onnx.py`**, **`core/src/freqid_core/config.py`**, **`core/src/freqid_core/errors.py`**:
  - Created for the FreqID project
  - Copyright: Copyright (c) 2026 FreqID Authors
  - License: Apache License, Version 2.0
