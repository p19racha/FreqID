# Phase 1 Assets & Dataset Licensing Audit

This document records the license, origin, usage restrictions, and commercial viability for all datasets, benchmark suites, and pretrained model weights considered or utilized during Phase 1.

## Asset Registry

| Asset Name | Asset Type | Source / Origin | Declared License / Terms | Commercial Viability | Research Use Conditions |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **BUPT-EqualizedFace** | Training Dataset | Beijing University of Posts and Telecommunications (BUPT) / RFW Project | Academic Research Only (Free for non-commercial research with signed agreement) | **NO** (Strictly non-commercial) | Requires formal citation of Deng et al., 2020. Redistribution prohibited. |
| **MS1M-ArcFace (MS1Mv2)** | Training Dataset | DeepInsight / InsightFace (cleaned MS-Celeb-1M) | Non-commercial research only (Microsoft original terms apply) | **NO** (Microsoft retracted original dataset; derivatives research-only) | Cannot be packaged with commercial products. |
| **CASIA-WebFace** | Training Dataset | Institute of Automation, Chinese Academy of Sciences (CASIA) | Academic Research Only | **NO** (Academic research agreement required) | Citation required. Commercial exploitation prohibited. |
| **LFW (Labeled Faces in the Wild)** | Benchmark Dataset | University of Massachusetts, Amherst | Non-commercial educational / research | **NO** (Research / benchmark comparison only) | Permitted for evaluating algorithm accuracy. |
| **CFP-FP (Celebrities in Frontal-Profile)** | Benchmark Dataset | University of Maryland | Research Only | **NO** | Research benchmark protocol. |
| **AgeDB-30** | Benchmark Dataset | Imperial College London | Academic research purposes only | **NO** | Subject to non-commercial license. |
| **TFace Baseline Checkpoints (IR_50, IR_101)** | Model Weights | Tencent Youtu Lab (Google Drive links) | Apache-2.0 (code repo) / Derived from MS1Mv2 | **RESTRICTED** | Weights inherit training data restrictions (MS1Mv2 research terms). |
| **PartialFace Pretrained Checkpoint** | Model Weights | **None provided** by authors | N/A (Must be trained) | Dependent on training data used | Training on synthetic or commercially cleared datasets (e.g., Synthetic Faces / CC-BY) is required for commercial release. |

---

## Implications for FreqID Production Release (Phase 9 & Beyond)

> [!WARNING]
> Because standard face recognition datasets (BUPT, MS1M, CASIA-WebFace) are restricted to academic/non-commercial research, **FreqID cannot distribute weights pre-trained on these datasets for commercial self-hosted deployments**.
> 
> For the final production system:
> 1. In Phase 1–2, use research datasets strictly to reproduce and measure baseline algorithmic parity with the ICCV 2023 paper.
> 2. For production release, train or provide recipes for training on synthetic identity datasets (e.g. DigiFace-1M, SynFace, UIFace) or commercially licensed biometric datasets.
