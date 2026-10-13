#!/usr/bin/env python3
"""
sanity_check.py: Visual and structural verification of the PartialFace data pipeline.

Verifies:
1. Loads samples through the actual PartialFace dataloader (AugmentedMultiDataset).
2. Applies Block Discrete Cosine Transform (BDCT), channel pruning, and randomized subset sampling.
3. Saves 'before' and 'after' images in freqid/research/outputs/sanity/:
   - face_spatial_before.png: The original aligned 112x112 spatial RGB face image.
   - face_reconstructed_after_pruning.png: Visual reconstruction demonstrating that human-perceivable
     facial information is eliminated when low frequencies are pruned.
   - face_frequency_channels_montage.png: Grid visualization of the 27 extracted frequency channel slices.
4. Asserts and prints tensor shapes at each step.
"""

import os
import sys
import torch
import torchvision.transforms as transforms
import numpy as np
import cv2

# Add recognition directory to path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(REPO_ROOT, 'recognition'))

from tasks.partialface.utils import dct_transform, idct_transform, create_channel_subsets, form_training_batch
from tasks.partialface.base_task import AugmentedMultiDataset


def run_sanity_check(data_root='data/train_subset', output_dir='research/outputs/sanity'):
    os.makedirs(output_dir, exist_ok=True)
    print(f"=== Running PartialFace Data Pipeline Sanity Check ===")

    # 1. Verify Dataset Loading via AugmentedMultiDataset
    img_dir = os.path.join(data_root, 'images')
    idx_dir = os.path.join(data_root, 'index')
    dataset_name = 'subset100'

    rgb_mean = [0.5, 0.5, 0.5]
    rgb_std = [0.5, 0.5, 0.5]
    transform = transforms.Compose([
        transforms.ToPILImage(),
        transforms.ToTensor(),
        transforms.Normalize(mean=rgb_mean, std=rgb_std)
    ])

    print(f"[1/4] Initializing AugmentedMultiDataset from {data_root}...")
    dataset = AugmentedMultiDataset(
        data_root=data_root,
        index_root=idx_dir,
        names=[dataset_name],
        transform=transform,
        num_aug=3
    )
    dataset.make_dataset(shard=False)
    print(f"      Loaded dataset '{dataset_name}': {dataset.sample_nums[dataset_name]} augmented samples, {dataset.class_nums[dataset_name]} classes.")

    batch_list = [dataset[(dataset_name, i)] for i in range(4)]
    batch_images = torch.stack([item[0] for item in batch_list])
    batch_labels = torch.tensor([item[1] for item in batch_list])
    print(f"      Batch raw tensor shape: {batch_images.shape}, Labels: {batch_labels.tolist()}")
    assert batch_images.shape == (4, 3, 112, 112), f"Expected (4, 3, 112, 112), got {batch_images.shape}"

    # 2. Extract Single Image and Save "Before" (Spatial RGB)
    # Convert normalized [-1, 1] tensor back to [0, 255] uint8 RGB for saving
    raw_sample = batch_images[0]
    raw_rgb = ((raw_sample.permute(1, 2, 0).numpy() * 0.5 + 0.5) * 255.0).clip(0, 255).astype(np.uint8)
    raw_bgr = cv2.cvtColor(raw_rgb, cv2.COLOR_RGB2BGR)

    before_path = os.path.join(output_dir, 'face_spatial_before.png')
    cv2.imwrite(before_path, raw_bgr)
    print(f"[2/4] Saved raw spatial face image (Before): {before_path} (Shape: {raw_rgb.shape})")

    # 3. Frequency Domain Transformation & Low-Frequency Pruning Demonstration
    # Prune 10 human-perceivable low frequencies: [0, 1, 2, 3, 8, 9, 10, 16, 17, 24]
    chs_prune = [0, 1, 2, 3, 8, 9, 10, 16, 17, 24]
    sample_tensor = raw_sample.unsqueeze(0)  # (1, 3, 112, 112)

    # DCT with padding to visualize the inverse
    freq_padded = dct_transform(sample_tensor, chs_remove=chs_prune, chs_pad=True)
    reconstructed_spatial = idct_transform(freq_padded)  # (1, 3, 112, 112) in [0, 1]

    recon_rgb = (reconstructed_spatial[0].permute(1, 2, 0).detach().cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    recon_bgr = cv2.cvtColor(recon_rgb, cv2.COLOR_RGB2BGR)

    after_recon_path = os.path.join(output_dir, 'face_reconstructed_after_pruning.png')
    cv2.imwrite(after_recon_path, recon_bgr)
    print(f"[3/4] Saved low-frequency pruned reconstruction (After): {after_recon_path}")
    print(f"      (Notice: visual facial features, skin tone, eyes and structure are obscured)")

    # 4. PartialFace Training Batch Sampling (27-channel tensor)
    sampled_batch, sampled_labels = form_training_batch(batch_images, batch_labels)
    print(f"[4/4] Formed PartialFace training batch:")
    print(f"      Input shape: {batch_images.shape} (RGB 3x112x112)")
    print(f"      Output shape: {sampled_batch.shape} (Partial Frequency 27x112x112)")
    assert sampled_batch.shape == (4, 27, 112, 112), f"Expected (4, 27, 112, 112), got {sampled_batch.shape}"

    # Generate a 27-channel slice montage for inspectability
    # Normalize each channel slice to [0, 255] for visual verification
    channel_slices = sampled_batch[0].detach().cpu().numpy()  # (27, 112, 112)
    rows = []
    for r in range(3):  # 3 rows of 9 channels (Y, Cb, Cr high-frequency subsets)
        row_imgs = []
        for c in range(9):
            ch_idx = r * 9 + c
            ch_slice = channel_slices[ch_idx]
            ch_norm = cv2.normalize(ch_slice, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8U)
            # Add small border
            ch_bordered = cv2.copyMakeBorder(ch_norm, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=128)
            row_imgs.append(ch_bordered)
        rows.append(np.hstack(row_imgs))
    montage = np.vstack(rows)

    montage_path = os.path.join(output_dir, 'face_frequency_channels_montage.png')
    cv2.imwrite(montage_path, montage)
    print(f"      Saved 27-channel frequency slices montage: {montage_path} (Shape: {montage.shape})")

    print(f"\n[SUCCESS] Sanity check completed successfully. All artifacts written to {output_dir}")
    return before_path, after_recon_path, montage_path


if __name__ == '__main__':
    run_sanity_check()
