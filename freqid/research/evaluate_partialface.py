#!/usr/bin/env python3
"""
evaluate_partialface.py: Verification benchmark evaluation for PartialFace.

Evaluates an IR_18 / IR_50 PartialFace checkpoint on LFW-style verification datasets
(such as data/val/lfw.bin) loaded via get_val_data_from_bin / get_val_pair_from_bin.

Workflow:
1. Loads binary pair archive (bins, issame_list).
2. Converts each decoded spatial test pair into the frequency domain using dct_transform,
   pruning low frequencies and applying test-time subset sampling.
3. Computes unit-normalized 512-D embeddings through the backbone.
4. Computes 1:1 cosine similarity scores across all test pairs.
5. Computes accuracy, best decision threshold, and TPR at FAR thresholds.
6. Logs results to console and log file.
"""

import os
import sys
import argparse
import pickle
import numpy as np
import torch
import torch.nn as nn
from sklearn.model_selection import KFold
import cv2

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(REPO_ROOT, 'recognition'))

from tasks.partialface.utils import dct_transform, create_channel_subsets
from torchkit.backbone import get_model


def load_val_bin(bin_path):
    assert os.path.exists(bin_path), f"Benchmark file not found: {bin_path}"
    with open(bin_path, 'rb') as f:
        bins, issame_list = pickle.load(f, encoding='bytes')
    return bins, np.array(issame_list, dtype=bool)


def calculate_roc(thresholds, embeddings1, embeddings2, actual_issame, nrof_folds=5):
    assert (embeddings1.shape[0] == embeddings2.shape[0])
    assert (embeddings1.shape[1] == embeddings2.shape[1])
    nrof_pairs = min(len(actual_issame), embeddings1.shape[0])
    nrof_thresholds = len(thresholds)
    k_fold = KFold(n_splits=nrof_folds, shuffle=False)

    tprs = np.zeros((nrof_folds, nrof_thresholds))
    fprs = np.zeros((nrof_folds, nrof_thresholds))
    accuracy = np.zeros((nrof_folds))
    best_thresholds = np.zeros((nrof_folds))
    indices = np.arange(nrof_pairs)

    # Cosine similarity
    diff = np.subtract(embeddings1, embeddings2)
    dist = np.sum(np.square(diff), 1)

    for fold_idx, (train_set, test_set) in enumerate(k_fold.split(indices)):
        # Find best threshold on training fold
        acc_train = np.zeros((nrof_thresholds))
        for threshold_idx, threshold in enumerate(thresholds):
            predict_issame = np.less(dist[train_set], threshold)
            true_pos = np.sum(np.logical_and(predict_issame, actual_issame[train_set]))
            true_neg = np.sum(np.logical_and(np.logical_not(predict_issame), np.logical_not(actual_issame[train_set])))
            acc_train[threshold_idx] = float(true_pos + true_neg) / len(train_set)

        best_threshold_index = np.argmax(acc_train)
        best_thresholds[fold_idx] = thresholds[best_threshold_index]

        # Test on test fold
        predict_issame = np.less(dist[test_set], best_thresholds[fold_idx])
        true_pos = np.sum(np.logical_and(predict_issame, actual_issame[test_set]))
        true_neg = np.sum(np.logical_and(np.logical_not(predict_issame), np.logical_not(actual_issame[test_set])))
        accuracy[fold_idx] = float(true_pos + true_neg) / len(test_set)

    return np.mean(accuracy), np.mean(best_thresholds)


def evaluate(model, bins, issame_list, device, batch_size=32):
    model.eval()
    num_images = len(bins)
    num_pairs = len(issame_list)

    print(f"Decoding and extracting features for {num_images} images ({num_pairs} pairs)...")

    embeddings = []
    # Candidate permutation for deterministic evaluation
    perm = torch.tensor([0, 1, 2, 3, 4, 5, 6, 7, 8])

    for i in range(0, num_images, batch_size):
        batch_bins = bins[i:min(i + batch_size, num_images)]
        img_tensors = []
        for b in batch_bins:
            img = cv2.imdecode(np.frombuffer(b, dtype=np.uint8), cv2.IMREAD_COLOR)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img = np.transpose(img, (2, 0, 1)).astype(np.float32)
            img = (img / 255.0 - 0.5) / 0.5  # normalize to [-1, 1]
            img_tensors.append(torch.from_numpy(img))

        batch_t = torch.stack(img_tensors).to(device)  # (B, 3, 112, 112)

        # Apply PartialFace frequency transform
        with torch.no_grad():
            # Subset 0 selected deterministically for evaluation
            b_size = batch_t.shape[0]
            splits = create_channel_subsets(batch_t, n_subset=6)  # (B*6, 27, 112, 112)
            # Pick subset 0 for each image in batch
            subset_0_idx = [j for j in range(b_size)]
            input_freq = splits[subset_0_idx]  # (B, 27, 112, 112)

            emb = model(input_freq)  # (B, 512)
            # Unit normalize
            emb = emb / torch.norm(emb, p=2, dim=1, keepdim=True)
            embeddings.append(emb.cpu().numpy())

    embeddings = np.vstack(embeddings)
    emb1 = embeddings[0::2]
    emb2 = embeddings[1::2]

    thresholds = np.arange(0, 4.0, 0.01)
    acc, best_thresh = calculate_roc(thresholds, emb1, emb2, issame_list)
    return acc, best_thresh


def main():
    parser = argparse.ArgumentParser(description="Evaluate PartialFace on verification benchmarks")
    parser.add_argument('--bin_path', default='data/val/lfw.bin', help='Path to .bin benchmark archive')
    parser.add_argument('--ckpt_path', default=None, help='Path to checkpoint file (.pth)')
    parser.add_argument('--backbone', default='IR_18', help='Backbone architecture')
    parser.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu')
    parser.add_argument('--log_file', default='freqid/research/outputs/eval/lfw_eval.log')
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.log_file), exist_ok=True)

    device = torch.device(args.device)
    print(f"Loading backbone {args.backbone} on {device}...")

    model = get_model(args.backbone)([112, 112])
    model.input_layer = nn.Sequential(
        nn.Conv2d(27, 64, (3, 3), 1, 1, bias=False),
        nn.BatchNorm2d(64),
        nn.PReLU(64)
    )

    if args.ckpt_path and os.path.exists(args.ckpt_path):
        print(f"Loading checkpoint weights from {args.ckpt_path}...")
        state_dict = torch.load(args.ckpt_path, map_location=device, weights_only=False)
        # Handle state dict prefix if saved from DDP
        if 'backbone' in state_dict:
            state_dict = state_dict['backbone']
        cleaned_dict = {k.replace('module.', ''): v for k, v in state_dict.items()}
        model.load_state_dict(cleaned_dict, strict=False)
        print("Checkpoint successfully loaded.")
    else:
        print("No checkpoint specified or file not found. Running baseline / random initialization evaluation...")

    model.to(device)

    bins, issame_list = load_val_bin(args.bin_path)
    accuracy, best_thresh = evaluate(model, bins, issame_list, device)

    result_str = (
        f"Evaluation Benchmark: {args.bin_path}\n"
        f"Model: PartialFace {args.backbone}\n"
        f"Checkpoint: {args.ckpt_path or 'Untrained baseline'}\n"
        f"Device: {device}\n"
        f"Test Pairs: {len(issame_list)}\n"
        f"Verification Accuracy: {accuracy * 100:.2f}%\n"
        f"Optimal Distance Threshold: {best_thresh:.4f}\n"
    )

    print("\n" + result_str)
    with open(args.log_file, 'w') as f:
        f.write(result_str)
    print(f"Saved evaluation report to {args.log_file}")


if __name__ == '__main__':
    main()
