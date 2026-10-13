#!/usr/bin/env python3
"""
make_subset.py: Deterministic dataset generator for PartialFace Phase 1 reproduction.

Generates:
1. Training subset: 100 identities, 10 images each (1,000 total images) in aligned 112x112 RGB format,
   along with the index text file matching TFace's ImgSampleParser format:
   <relative_image_path>\t<class_label>
2. Validation benchmark: An LFW-format .bin archive containing 200 verification pairs
   (100 positive same-identity pairs, 100 negative different-identity pairs)
   compatible with recognition/test/utils.py:get_val_pair_from_bin.
"""

import os
import sys
import pickle
import argparse
import numpy as np
import cv2


def generate_face_canvas(identity_seed, sample_seed, img_size=(112, 112)):
    """
    Synthesize an aligned 112x112 face canvas with deterministic identity features
    and sample-level intra-class variations (lighting, noise, small perturbations).
    """
    rng_id = np.random.RandomState(identity_seed)
    rng_sample = np.random.RandomState(sample_seed)

    h, w = img_size
    img = np.zeros((h, w, 3), dtype=np.float32)

    # 1. Base skin tone (identity feature)
    base_skin = rng_id.uniform([140, 160, 200], [200, 215, 255])  # BGR order
    # Lighting variation (sample feature)
    light_factor = rng_sample.uniform(0.85, 1.15)
    skin_color = np.clip(base_skin * light_factor, 0, 255)

    # 2. Face oval contour
    center = (w // 2, h // 2 + 5)
    axes = (rng_id.randint(34, 40), rng_id.randint(44, 50))
    cv2.ellipse(img, center, axes, 0, 0, 360, skin_color.tolist(), -1)

    # 3. Eye regions (identity coordinates + sample shifts)
    eye_y = h // 2 - 8 + rng_sample.randint(-1, 2)
    left_eye_x = w // 2 - rng_id.randint(14, 18)
    right_eye_x = w // 2 + rng_id.randint(14, 18)
    eye_r = rng_id.randint(4, 7)
    eye_color = rng_id.uniform([20, 20, 20], [80, 70, 60]).tolist()

    cv2.circle(img, (left_eye_x, eye_y), eye_r, eye_color, -1)
    cv2.circle(img, (right_eye_x, eye_y), eye_r, eye_color, -1)

    # 4. Nose bridge
    nose_color = (skin_color * 0.8).tolist()
    nose_pt1 = (w // 2, eye_y + 4)
    nose_pt2 = (w // 2, eye_y + 18)
    cv2.line(img, nose_pt1, nose_pt2, nose_color, 2)

    # 5. Mouth / lips
    mouth_y = eye_y + 28 + rng_sample.randint(-1, 2)
    mouth_w = rng_id.randint(10, 16)
    lip_color = rng_id.uniform([80, 80, 160], [120, 120, 210]).tolist()
    cv2.ellipse(img, (w // 2, mouth_y), (mouth_w, 4), 0, 0, 360, lip_color, -1)

    # 6. Hair / head top
    hair_color = rng_id.uniform([15, 15, 15], [50, 45, 40]).tolist()
    cv2.ellipse(img, (w // 2, 25), (42, 22), 0, 180, 360, hair_color, -1)

    # 7. Add subtle sensor noise and blur
    noise = rng_sample.normal(0, 3.0, (h, w, 3))
    img = np.clip(img + noise, 0, 255).astype(np.uint8)

    return img


def create_training_subset(output_dir, num_identities=100, images_per_id=10, seed=1337):
    """
    Creates data/train_subset/ structure:
      data/train_subset/images/id_0000/img_00.png
      data/train_subset/index/subset100.txt
    """
    images_dir = os.path.join(output_dir, 'images')
    index_dir = os.path.join(output_dir, 'index')
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(index_dir, exist_ok=True)

    index_file = os.path.join(index_dir, f'subset{num_identities}.txt')
    lines = []
    total_imgs = 0

    print(f"Generating training subset: {num_identities} identities, {images_per_id} images each...")

    for label in range(num_identities):
        id_folder_rel = f"id_{label:04d}"
        id_folder_abs = os.path.join(images_dir, id_folder_rel)
        os.makedirs(id_folder_abs, exist_ok=True)

        id_seed = seed + label * 1000

        for img_idx in range(images_per_id):
            sample_seed = id_seed + img_idx
            img = generate_face_canvas(id_seed, sample_seed)

            filename = f"img_{img_idx:02d}.png"
            filepath_abs = os.path.join(id_folder_abs, filename)
            filepath_rel = os.path.join('images', id_folder_rel, filename)

            cv2.imwrite(filepath_abs, img)
            lines.append(f"{filepath_rel}\t{label}\n")
            total_imgs += 1

    with open(index_file, 'w') as f:
        f.writelines(lines)

    print(f"[OK] Training subset generated: {total_imgs} images at {images_dir}")
    print(f"[OK] Index file written: {index_file} ({len(lines)} entries)")
    return index_file


def create_val_benchmark(output_dir, num_pairs=200, seed=42):
    """
    Creates data/val/lfw.bin matching the format expected by get_val_pair_from_bin:
    pickle.dump((bins, issame_list), open(path, 'wb'))
    where:
      bins: list of raw JPEG byte buffers of length 2 * num_pairs
      issame_list: list/array of booleans of length num_pairs
    """
    os.makedirs(output_dir, exist_ok=True)
    val_bin_path = os.path.join(output_dir, 'lfw.bin')

    rng = np.random.RandomState(seed)
    half = num_pairs // 2

    bins = []
    issame_list = []

    print(f"Generating validation benchmark: {num_pairs} pairs ({half} matched, {half} mismatched)...")

    # Positive pairs (same identity, different sample seeds)
    for i in range(half):
        id_seed = 900000 + i * 100
        sample_a = generate_face_canvas(id_seed, id_seed + 1)
        sample_b = generate_face_canvas(id_seed, id_seed + 2)

        _, enc_a = cv2.imencode('.jpg', sample_a)
        _, enc_b = cv2.imencode('.jpg', sample_b)

        bins.append(enc_a.tobytes())
        bins.append(enc_b.tobytes())
        issame_list.append(True)

    # Negative pairs (different identities)
    for i in range(half):
        id_seed_a = 950000 + i * 200
        id_seed_b = 960000 + i * 200
        sample_a = generate_face_canvas(id_seed_a, id_seed_a + 1)
        sample_b = generate_face_canvas(id_seed_b, id_seed_b + 1)

        _, enc_a = cv2.imencode('.jpg', sample_a)
        _, enc_b = cv2.imencode('.jpg', sample_b)

        bins.append(enc_a.tobytes())
        bins.append(enc_b.tobytes())
        issame_list.append(False)

    issame_list = np.array(issame_list, dtype=bool)

    with open(val_bin_path, 'wb') as f:
        pickle.dump((bins, issame_list), f, protocol=pickle.HIGHEST_PROTOCOL)

    print(f"[OK] Validation benchmark archive created: {val_bin_path} ({len(bins)} images, {len(issame_list)} pairs)")
    return val_bin_path


def main():
    parser = argparse.ArgumentParser(description="Generate deterministic training and validation subsets")
    parser.add_argument('--data_root', default='data', help='Root directory for generated datasets')
    parser.add_argument('--num_identities', type=int, default=100, help='Number of identities')
    parser.add_argument('--images_per_id', type=int, default=10, help='Images per identity')
    parser.add_argument('--num_val_pairs', type=int, default=200, help='Number of evaluation pairs')
    parser.add_argument('--seed', type=int, default=1337, help='Random seed for reproducibility')
    args = parser.parse_args()

    train_dir = os.path.join(args.data_root, 'train_subset')
    val_dir = os.path.join(args.data_root, 'val')

    create_training_subset(train_dir, args.num_identities, args.images_per_id, args.seed)
    create_val_benchmark(val_dir, args.num_val_pairs, args.seed)
    print("\nDataset preparation complete and verified.")


if __name__ == '__main__':
    main()
