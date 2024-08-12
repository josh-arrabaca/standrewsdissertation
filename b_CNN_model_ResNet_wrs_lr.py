# Import libraries
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim import lr_scheduler
import torch.backends.cudnn as cudnn
import numpy as np
import torchvision
from torchvision import datasets, models, transforms
import matplotlib.pyplot as plt
import time
import os
from PIL import Image
from tempfile import TemporaryDirectory
from torch.utils.data import DataLoader
import pandas as pd
from torch.utils.data import WeightedRandomSampler

cudnn.benchmark = True
plt.ion()   # interactive mode

# Set 'random' seed
torch.manual_seed(220029955)

# Welcome message
print("Welcome! We will train the last layer of a pre-trained CNN model.\n")


# Define the transforms needed 
data_transforms = transforms.Compose([
        transforms.Resize([224,224]), # Minimum size needed for Densenet
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]) # Required normalisation for Densenet
    ])

# Get the dataset from the images created from the wav files
dataset = datasets.ImageFolder(os.path.join("data", "images"), transform=data_transforms)

# Define the classes (Insular and Pelagic)
classes = dataset.classes

# Split the data into train, val and test sets
train_size = int(0.6 * len(dataset))
val_size = int((len(dataset) - train_size) / 2)
test_size = val_size
train_dataset, val_dataset, test_dataset = torch.utils.data.random_split(dataset, [train_size, val_size, test_size])
print(f"The dataset consists of {train_size + val_size + test_size} datapoints, split as follows:")
print(f"Train set: {train_size} \nValidation set: {val_size} \nTest size: {test_size}\n")

# Define the device to be used for training
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print(f'The device being used is: {device}\n')

# Define the batch size and number of epochs based on the device
if str(device) == "cuda:0":
    batch_size = 64
    num_epochs = 24
else:
    batch_size = 20
    num_epochs = 3

# Dataloaders
train_dataloader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
val_dataloader = DataLoader(val_dataset, batch_size=batch_size, shuffle=True)
test_dataloader = DataLoader(test_dataset, batch_size=batch_size, shuffle=True)


# Define function to create a balanced sampler
# https://www.maskaravivek.com/post/pytorch-weighted-random-sampler/
def balanced_sampler(full_dataset, train_dataset):
    # Find number of samples per class
    y_train_indices = train_dataset.indices
    y_train = [full_dataset.targets[i] for i in y_train_indices]
    class_sample_count = np.array([len(np.where(y_train == t)[0]) for t in np.unique(y_train)])

    # Find weights per class
    weight = 1. / class_sample_count
    samples_weight = np.array([weight[t] for t in y_train])
    samples_weight = torch.from_numpy(samples_weight)

    # Define sampler
    sampler = WeightedRandomSampler(samples_weight.type('torch.DoubleTensor'), len(samples_weight))

    return sampler

# Create a balanced sampler
sampler = balanced_sampler(dataset, train_dataset)
train_dataloader = DataLoader(train_dataset, batch_size=batch_size, sampler=sampler)

dataloaders = {"train": train_dataloader,
               "val": val_dataloader}

dataset_sizes = {"train": len (train_dataset),
                 "val": len(test_dataset)}


# Originally taken from the Pytorch tutorial by Sasank Chilamkurthy
def train_model(model, criterion, optimizer, scheduler, num_epochs=25):
    train_losses = []
    val_losses = []
    since = time.time()
    
    # Create a temporary directory to save training checkpoints
    with TemporaryDirectory() as tempdir:
        best_model_params_path = os.path.join(tempdir, 'best_model_params.pt')
    
        torch.save(model.state_dict(), best_model_params_path)
        best_acc = 0.0

        for epoch in range(num_epochs):
            print(f'Epoch {epoch}/{num_epochs - 1}')
            print('-' * 10)

            # Each epoch has a training and validation phase
            for phase in ['train', 'val']:
                if phase == 'train':
                    model.train()  # Set model to training mode
                else:
                    model.eval()   # Set model to evaluate mode

                running_loss = 0.0
                running_corrects = 0

                # Iterate over data.
                for inputs, labels in dataloaders[phase]:
                    inputs = inputs.to(device)
                    labels = labels.to(device)

                    # zero the parameter gradients
                    optimizer.zero_grad()

                    # forward
                    # track history if only in train
                    with torch.set_grad_enabled(phase == 'train'):
                        outputs = model(inputs)
                        _, preds = torch.max(outputs, 1)
                        loss = criterion(outputs, labels)

                        # backward + optimize only if in training phase
                        if phase == 'train':
                            loss.backward()
                            optimizer.step()

                    # statistics
                    running_loss += loss.item() * inputs.size(0)
                    running_corrects += torch.sum(preds == labels.data)
                if phase == 'train':
                    scheduler.step()

                epoch_loss = running_loss / dataset_sizes[phase]
                epoch_acc = running_corrects.double() / dataset_sizes[phase]

                if phase == 'train':
                     train_losses.append(epoch_loss)
                else:
                     val_losses.append(epoch_loss)
                print(f'{phase} Loss: {epoch_loss:.4f} Acc: {epoch_acc:.4f}')

                # deep copy the model
                if phase == 'val' and epoch_acc > best_acc:
                    best_acc = epoch_acc
                    torch.save(model.state_dict(), best_model_params_path)

            print()

        time_elapsed = time.time() - since
        print(f'Training complete in {time_elapsed // 60:.0f}m {time_elapsed % 60:.0f}s\n\n')
        print(f'The best val accuracy score is: {best_acc:4f}\n\n')

        # Plot the losses
        plt.plot(train_losses, 'b', label='Training Loss')
        plt.plot(val_losses, 'r--', label='Validation Loss')
        plt.legend(loc='upper right')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.title("Model Loss over Epochs for LR=" + str(lr))
        plt.savefig("losses_"+str(lr)+".png", bbox_inches='tight')
        plt.close()

        # load best model weights
        model.load_state_dict(torch.load(best_model_params_path))
    return model


# We load Resnet since this had the best base accuracy
model_conv = torchvision.models.resnet18(weights='IMAGENET1K_V1')

# This part does the training on the final layer only
for param in model_conv.parameters():
    param.requires_grad = False

# Parameters of newly constructed modules have requires_grad=True by default
num_ftrs = model_conv.fc.in_features
model_conv.fc = nn.Linear(num_ftrs, 2)

model_conv = model_conv.to(device)

criterion = nn.CrossEntropyLoss()

# Here we try some different learning rates
learning_rates = [0.0005, 0.001, 0.005, 0.01, 0.05, 0.1]

for learning_rate in learning_rates:
    lr = learning_rate
    optimizer_conv = optim.SGD(model_conv.fc.parameters(), lr=lr, momentum=0.9)

    # Decay LR by a factor of 0.1 every 7 epochs
    exp_lr_scheduler = lr_scheduler.StepLR(optimizer_conv, step_size=7, gamma=0.1)

    # Now train the model, and see the loss and accuracy scores for the different learning rates
    model_conv = train_model(model_conv, criterion, optimizer_conv,
                            exp_lr_scheduler, num_epochs=num_epochs)
