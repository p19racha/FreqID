#!/usr/bin/env python3
"""
train_partialface.py: Deterministic, production-grade training loop for PartialFace reproduction.

Trains PartialFace IR_18 on a verified dataset subset using ArcFace angular margin loss
and the official Block DCT + random channel subset sampling pipeline.

Outputs:
- freqid/research/outputs/train/train.log: Timestamped metrics (loss, top-1, top-5, step time, GPU RAM).
- freqid/research/outputs/checkpoints/partialface_ir18_epoch5.pth: Checkpoint for evaluation and inference.
"""

import os
import sys
import time
import math
import argparse
import logging
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.transforms as transforms
from torch.utils.data import DataLoader

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(REPO_ROOT, 'recognition'))

from tasks.partialface.utils import form_training_batch
from tasks.partialface.base_task import AugmentedMultiDataset
from torchkit.backbone import get_model


class ArcFaceHead(nn.Module):
    """
    ArcFace head implementation: cos(theta + m) with scale s=64.0 and margin m=0.5.
    """
    def __init__(self, in_features=512, out_features=100, s=64.0, m=0.5):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.s = s
        self.m = m
        self.weight = nn.Parameter(torch.FloatTensor(out_features, in_features))
        nn.init.xavier_uniform_(self.weight)

        self.cos_m = math.cos(m)
        self.sin_m = math.sin(m)
        self.th = math.cos(math.pi - m)
        self.mm = math.sin(math.pi - m) * m

    def forward(self, input, label):
        cosine = F.linear(F.normalize(input), F.normalize(self.weight))
        sine = torch.sqrt((1.0 - torch.pow(cosine, 2)).clamp(0, 1))
        phi = cosine * self.cos_m - sine * self.sin_m
        phi = torch.where(cosine > self.th, phi, cosine - self.mm)

        one_hot = torch.zeros(cosine.size(), device=input.device)
        one_hot.scatter_(1, label.view(-1, 1).long(), 1)
        output = (one_hot * phi) + ((1.0 - one_hot) * cosine)
        output *= self.s
        return output, cosine


def accuracy(output, target, topk=(1,)):
    with torch.no_grad():
        maxk = max(topk)
        batch_size = target.size(0)

        _, pred = output.topk(maxk, 1, True, True)
        pred = pred.t()
        correct = pred.eq(target.view(1, -1).expand_as(pred))

        res = []
        for k in topk:
            correct_k = correct[:k].reshape(-1).float().sum(0, keepdim=True)
            res.append(correct_k.mul_(100.0 / batch_size).item())
        return res


def train(args):
    os.makedirs(args.log_dir, exist_ok=True)
    os.makedirs(args.ckpt_dir, exist_ok=True)

    log_path = os.path.join(args.log_dir, 'train.log')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_path, mode='w'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.info(f"Starting PartialFace Reproduction Training Run")
    logging.info(f"Arguments: {vars(args)}")

    device = torch.device(args.device)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available() and device.type == 'cuda':
        torch.cuda.manual_seed(args.seed)

    # 1. Dataset & Dataloader
    transform = transforms.Compose([
        transforms.ToPILImage(),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])
    ])

    class MultiDatasetAdapter(torch.utils.data.Dataset):
        def __init__(self, multi_ds, name):
            self.multi_ds = multi_ds
            self.name = name
            self.sample_num = multi_ds.sample_nums[name]
        def __len__(self):
            return self.sample_num
        def __getitem__(self, idx):
            return self.multi_ds[(self.name, idx)]

    dataset = AugmentedMultiDataset(
        data_root=args.data_root,
        index_root=os.path.join(args.data_root, 'index'),
        names=[args.dataset_name],
        transform=transform,
        num_aug=args.num_aug
    )
    dataset.make_dataset(shard=False)
    num_classes = dataset.class_nums[args.dataset_name]
    sample_count = dataset.sample_nums[args.dataset_name]
    logging.info(f"Loaded dataset '{args.dataset_name}': {sample_count} samples across {num_classes} classes.")

    wrapped_dataset = MultiDatasetAdapter(dataset, args.dataset_name)
    train_loader = DataLoader(
        wrapped_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=(device.type == 'cuda'),
        drop_last=True
    )

    # 2. Model & Head
    backbone = get_model(args.backbone)([112, 112])
    # Adapt input layer to 27 channels (9 channels * 3 color planes)
    backbone.input_layer = nn.Sequential(
        nn.Conv2d(args.num_chs * 3, 64, (3, 3), 1, 1, bias=False),
        nn.BatchNorm2d(64),
        nn.PReLU(64)
    )
    backbone.to(device)

    head = ArcFaceHead(in_features=512, out_features=num_classes, s=64.0, m=0.5).to(device)
    criterion = nn.CrossEntropyLoss().to(device)

    optimizer = torch.optim.SGD(
        list(backbone.parameters()) + list(head.parameters()),
        lr=args.lr,
        momentum=args.momentum,
        weight_decay=args.weight_decay
    )
    scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer, milestones=[3, 4], gamma=0.1)

    # 3. Training Loop
    total_steps = len(train_loader) * args.epochs
    step_count = 0
    start_total_time = time.time()

    logging.info(f"Training for {args.epochs} epochs, {len(train_loader)} steps per epoch (Total: {total_steps} steps).")

    for epoch in range(1, args.epochs + 1):
        backbone.train()
        head.train()
        epoch_loss = 0.0
        epoch_top1 = 0.0
        epoch_top5 = 0.0

        for step, (inputs, labels) in enumerate(train_loader):
            step_start = time.time()
            step_count += 1

            inputs = inputs.to(device)
            labels = labels.to(device)

            # Apply PartialFace frequency transform and sampling
            sampled_inputs, sampled_labels = form_training_batch(inputs, labels)

            optimizer.zero_grad()
            embeddings = backbone(sampled_inputs)
            logits, raw_cos = head(embeddings, sampled_labels)
            loss = criterion(logits, sampled_labels)

            loss.backward()
            optimizer.step()

            step_time = (time.time() - step_start) * 1000.0
            prec1, prec5 = accuracy(raw_cos.data, sampled_labels, topk=(1, 5))

            epoch_loss += loss.item()
            epoch_top1 += prec1
            epoch_top5 += prec5

            peak_gpu_mem = torch.cuda.max_memory_allocated() / (1024 * 1024) if device.type == 'cuda' else 0.0

            if step % args.print_freq == 0 or step == len(train_loader) - 1:
                logging.info(
                    f"Epoch [{epoch}/{args.epochs}] Step [{step+1}/{len(train_loader)}] "
                    f"Loss: {loss.item():.4f} | Prec@1: {prec1:.2f}% | Prec@5: {prec5:.2f}% | "
                    f"LR: {optimizer.param_groups[0]['lr']:.4f} | "
                    f"Time/Step: {step_time:.1f}ms | Peak GPU RAM: {peak_gpu_mem:.1f}MB"
                )

        scheduler.step()
        avg_loss = epoch_loss / len(train_loader)
        avg_top1 = epoch_top1 / len(train_loader)
        avg_top5 = epoch_top5 / len(train_loader)
        logging.info(
            f"=== Epoch {epoch} Completed | Avg Loss: {avg_loss:.4f} | Avg Prec@1: {avg_top1:.2f}% | Avg Prec@5: {avg_top5:.2f}% ==="
        )

    # 4. Save Checkpoint
    ckpt_path = os.path.join(args.ckpt_dir, f'partialface_{args.backbone.lower()}_epoch{args.epochs}.pth')
    torch.save({
        'epoch': args.epochs,
        'backbone': backbone.state_dict(),
        'head': head.state_dict(),
        'optimizer': optimizer.state_dict(),
        'args': vars(args)
    }, ckpt_path)
    total_time = time.time() - start_total_time
    logging.info(f"Training successfully finished in {total_time:.2f}s.")
    logging.info(f"Saved checkpoint to {ckpt_path} (Size: {os.path.getsize(ckpt_path)/(1024*1024):.2f} MB).")
    return ckpt_path


def main():
    parser = argparse.ArgumentParser(description="PartialFace Training Loop")
    parser.add_argument('--data_root', default='data/train_subset', help='Root dataset directory')
    parser.add_argument('--dataset_name', default='subset100', help='Dataset name')
    parser.add_argument('--backbone', default='IR_18', help='Backbone network')
    parser.add_argument('--num_chs', type=int, default=9, help='Number of frequency channels per plane')
    parser.add_argument('--num_aug', type=int, default=3, help='Data augmentation multiplier')
    parser.add_argument('--batch_size', type=int, default=32, help='Batch size per iteration')
    parser.add_argument('--epochs', type=int, default=5, help='Number of epochs')
    parser.add_argument('--lr', type=float, default=0.05, help='Initial learning rate')
    parser.add_argument('--momentum', type=float, default=0.9, help='Momentum')
    parser.add_argument('--weight_decay', type=float, default=0.0005, help='Weight decay')
    parser.add_argument('--num_workers', type=int, default=2, help='Dataloader workers')
    parser.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu')
    parser.add_argument('--seed', type=int, default=1337, help='Random seed')
    parser.add_argument('--print_freq', type=int, default=10, help='Log frequency')
    parser.add_argument('--log_dir', default='freqid/research/outputs/train', help='Log directory')
    parser.add_argument('--ckpt_dir', default='freqid/research/outputs/checkpoints', help='Checkpoint directory')
    args = parser.parse_args()

    train(args)


if __name__ == '__main__':
    main()
