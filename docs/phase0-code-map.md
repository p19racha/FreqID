# Phase 0 Code Map: Tencent/TFace & PartialFace

## 1. Repository Overview

The repository is organized into five top-level domain modules:
- `recognition/`: Face recognition algorithms, backbone architectures, loss functions, distributed training, testing, and deployment converters.
- `security/`: Face anti-spoofing, deepfake detection, and adversarial attack/defense methods.
- `quality/`: Unsupervised face image quality assessment (SDD-FIQA).
- `attribute/`: Facial expression and dynamic attribute recognition (M3DFEL).
- `generation/`: Synthetic face intra-class diversity generation (UIFace).

### Structure of `recognition/` (Depth 2)

```
recognition/
├── local_train.sh               # Root training launch script
├── requirements.txt             # Root requirements (dareblopy)
├── train.py                     # Root distributed training script
├── train.yaml                   # Baseline training configuration
├── README.md                    # Module documentation and benchmark model zoo
├── deploy/                      # Inference deployment engines & ONNX converters
│   ├── CMakeLists.txt
│   ├── README.md
│   ├── converter/
│   ├── core/
│   ├── data/
│   ├── scripts/
│   └── test/
├── doc/                         # Architecture figures and logos
│   ├── framework.png
│   └── logo.png
├── tasks/                       # Specialized research tasks and publications
│   ├── dctdp/                   # ECCV 2022: Frequency differential privacy
│   ├── duetface/                # ACM MM 2022: Channel splitting collaborative recognition
│   ├── ekd/                     # CVPR 2022: Evaluation-oriented KD
│   ├── minusface/               # CVPR 2024: Trainable feature subtraction
│   ├── partialface/             # ICCV 2023: Random frequency components (Core for FreqID)
│   └── slerpface/               # AAAI 2025: Hypersphere linear interpolation template protection
├── test/                        # Benchmark evaluation protocols
│   ├── datasets.py
│   ├── extract_features.py
│   ├── IJB_Evaluation.py
│   ├── README.md
│   ├── utils.py
│   ├── verification.py
│   └── verification_rfw.py
├── tools/                       # Dataset conversion and indexing utilities
│   ├── convert_new_index.py
│   ├── decode.py
│   └── img2tfrecord.py
└── torchkit/                    # Modular deep learning training framework
    ├── backbone/                # IR_18, IR_50, IR_101, MobileFaceNet, GhostNet, EfficientNet
    ├── data/                    # TFRecord and image dataset loaders and parsers
    ├── head/                    # ArcFace, CosFace, CurricularFace, PartialFC
    ├── hooks/                   # Checkpointing, logging, learning rate, summary hooks
    ├── loss/                    # DistCrossEntropy, Softmax, DDL
    ├── task/                    # BaseTask framework abstractions
    ├── tfrecord/                # Protobuf definitions for TFRecord storage
    └── util/                    # Distributed utilities, meters, and timers
```

---

## 2. Privacy-Preserving Tasks in Repository

| Task Folder | Method / Paper Title | Venue / Year | Approach Summary |
| :--- | :--- | :--- | :--- |
| `recognition/tasks/partialface` | **PartialFace**: *Privacy-Preserving Face Recognition Using Random Frequency Components* | ICCV 2023 | Prunes human-perceivable low frequencies via BDCT; trains and infers on randomly sampled high-frequency channel subsets. Core algorithm for FreqID. |
| `recognition/tasks/minusface` | **MinusFace**: *Privacy-Preserving Face Recognition Using Trainable Feature Subtraction* | CVPR 2024 | Subtracts model regeneration from input face to remove visual features, combined with random channel shuffling. Relies on `partialface.utils` for DCT. |
| `recognition/tasks/dctdp` | **DCT-DP**: *Privacy-Preserving Face Recognition with Learnable Privacy Budgets in Frequency Domain* | ECCV 2022 | Removes DC components in frequency domain and adds learned differential privacy noise budgets. |
| `recognition/tasks/duetface` | **DuetFace**: *Collaborative Privacy-Preserving Face Recognition via Channel Splitting in the Frequency Domain* | ACM MM 2022 | Splits frequency channels between client and server; client sends high frequencies with attention mask transfer. |
| `recognition/tasks/slerpface` | **SlerpFace**: *Face Template Protection via Spherical Linear Interpolation* | AAAI 2025 | Rotates face feature embeddings on the hypersphere to Gaussian noise distributions with channel dropout. |
| `recognition/tasks/ekd` | **EKD**: *Evaluation-oriented Knowledge Distillation for Deep Face Recognition* | CVPR 2022 | Optimizes student network directly on TPR/FPR verification margins. |

---

## 3. PartialFace Component Breakdown

The table below provides precise references for every architectural component of PartialFace:

| Component | File Path | Line Range | Notes |
| :--- | :--- | :--- | :--- |
| **Training Entry Point** | `recognition/tasks/partialface/train.py` | L253–L262 | Instantiates `TrainTask` from `train.yaml`, initializes distributed environment, and starts training. |
| **Training Launch Script** | `recognition/tasks/partialface/local_train.sh` | L1–L3 | Runs `python -u -m torch.distributed.launch --nproc_per_node=1 --nnodes=1 train.py` with `CUDA_VISIBLE_DEVICES='0'`. |
| **Evaluation Documentation** | `recognition/tasks/partialface/README.md` | L57–L59 | References `recognition/test/README.md` for standard evaluation procedures. |
| **Verification Test Script** | `recognition/test/verification.py` | L23–L95 | Evaluates checkpoint embeddings on 1:1 verification benchmarks (LFW, CFP-FP, AgeDB, CALFW, CPLFW). *(Note: Requires frequency adapter for PartialFace).* |
| **IJB 1:1 Evaluation** | `recognition/test/extract_features.py`<br>`recognition/test/IJB_Evaluation.py` | L1–L80<br>L1–L130 | Feature extraction and TAR@FAR computation on IJB-B and IJB-C benchmarks. |
| **Task Configuration** | `recognition/tasks/partialface/train.yaml` | L1–L56 | Specifies dataset paths (`DATA_ROOT`, `INDEX_ROOT`), `INPUT_SIZE: [112, 112]`, `BACKBONE_NAME: 'IR_18'`, `EMBEDDING_SIZE: 512`, `HEAD_NAME: "ArcFace"`, `LOSS_NAME: 'DistCrossEntropy'`, `NUM_AUG: 3`, `NUM_CHS: 9`. |
| **Block DCT Conversion** | `recognition/tasks/partialface/utils.py` | L7–L52 | `dct_transform()`: Converts spatial images $(B, 3, 112, 112)$ to YCbCr, unfolds into $8 \times 8$ blocks, executes `torchjpeg.dct.block_dct`, and outputs frequency tensors $(B, C, N_b, N_b, 64)$. |
| **Inverse DCT (IDCT)** | `recognition/tasks/partialface/utils.py` | L54–L76 | `idct_transform()`: Inverts 192 frequency channels back to spatial RGB image domain using `block_idct` and `F.fold` (used for reconstruction and visualization). |
| **Channel Pruning** | `recognition/tasks/partialface/utils.py` | L39–L47, L84–L86 | In `dct_transform` and `create_channel_subsets`, prunes 10 perceivable low-frequency channels per color channel: indices `[0, 1, 2, 3, 8, 9, 10, 16, 17, 24]`, leaving $64 - 10 = 54$ channels. |
| **Subset Partition ($\mathbf{S}$)** | `recognition/tasks/partialface/utils.py` | L88–L102 | Splits 54 remaining high-frequency channels into $n\_subset = 6$ non-overlapping subsets of $s = 9$ channels per color plane via fixed matrix $\mathbf{S}$. |
| **Random Subset Sampling & Permutation ($\mathbf{P}$)** | `recognition/tasks/partialface/utils.py` | L124–L164 | `form_training_batch()`: Binds identity `label % 20` to 3 allowed subsets out of 6 ($\binom{6}{3} = 20$), draws 1 subset per image via `torch.randint`, and applies a random permutation from $\mathbf{P}$ (3 candidate permutations). Returns $(B, 27, 112, 112)$ tensor ($9 \text{ channels} \times 3 \text{ YCbCr}$). |
| **Model Definition & Input Layer Adaptation** | `recognition/tasks/partialface/base_task.py` | L101–L111 | Overrides `self.backbone.input_layer` with `Conv2d(NUM_CHS * 3, 64, (3,3), 1, 1, bias=False)`, `BatchNorm2d(64)`, `PReLU(64)` to accept 27 frequency channels instead of 3 RGB channels. |
| **Backbone Architecture** | `recognition/torchkit/backbone/model_irse.py` | L64–L128 | `IR_18` / `IR_50` Modified ResNet with Improved Residual Units and PReLU activations. |
| **Loss Function** | `recognition/torchkit/loss/dist_cross_entropy.py`<br>`recognition/torchkit/head/arcface.py` | L8–L32<br>L18–L52 | Distributed Cross-Entropy loss combined with ArcFace additive angular margin ($s=64, m=0.5$). Initialized via `get_loss('DistCrossEntropy')` in `train.py:L214`. |
| **Training Loop** | `recognition/tasks/partialface/train.py` | L37–L202, L224–L251 | `loop_step()` & `train()`: Loops over epochs, transforms input batches into frequency subsets via `form_training_batch()`, computes backbone forward pass, gathers features with `AllGather`, computes ArcFace logits and loss, and updates gradients with optional AMP. |
| **Pretrained Weights** | `recognition/README.md` | L110–L120 | Only baseline models (IR_50, IR_101 on MS1Mv2 and IR_SE_101 on iCartoonFace) are linked via Google Drive. **No pretrained weights for PartialFace are provided in the repository.** |
