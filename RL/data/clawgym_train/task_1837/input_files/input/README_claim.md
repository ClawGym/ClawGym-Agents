# Validation Claim for Torchvision ResNet18 Pilot

We fine-tuned a Torchvision ResNet18 on a small product set and evaluated on 24 validation images.

Claimed top-1 validation accuracy: 87.5%

Files:
- predictions.csv: model outputs as class indices by image_id
- ground_truth.csv: true labels by image_id
- label_map.json: index-to-class mapping used at inference time
