from typing import Callable

import torch
from torch.utils.data import Dataset

from openrlhf.utils.utils import zero_pad_sequences

# keep support for conversations style
def preprocess_data(
    data, input_template=None, input_key="input", output_key=None, apply_chat_template=None, multiturn=False
):
    if apply_chat_template:
        if output_key:
            kill

        else:
            prompt = apply_chat_template(data[input_key][:-1], tokenize=False, add_generation_prompt=True)
            response = apply_chat_template(data[input_key], tokenize=False)[len(prompt) :]
    else:
        kill
    return prompt, response


class SFTDataset(Dataset):
    """
    Dataset for SFT model

    Args:
        dataset: dataset for SFT model
        tokenizer: tokenizer for SFT model
        max_length: max length of input
    """

    def __init__(
        self,
        dataset,
        tokenizer: Callable,
        max_length: int,
        strategy,
        input_template=None,
        pretrain_mode=False,
        num_processors=16,  # Specify the number of processors you want to use
        multiturn=False,
    ) -> None:
        super().__init__()
        self.tokenizer = tokenizer
        self.strategy = strategy
        self.pretrain_mode = pretrain_mode
        self.max_length = max_length
        self.multiturn = multiturn

        # chat template
        self.input_template = input_template
        self.input_key = getattr(self.strategy.args, "input_key", None)
        self.output_key = getattr(self.strategy.args, "output_key", None)
        self.apply_chat_template = getattr(self.strategy.args, "apply_chat_template", True)

        if self.apply_chat_template:
            self.apply_chat_template = self.tokenizer.apply_chat_template
            tokenizer_chat_template = getattr(self.strategy.args, "tokenizer_chat_template", None)
            if tokenizer_chat_template:
                self.tokenizer.chat_template = tokenizer_chat_template

        # Parallel loading datasets
        if not self.multiturn:
            processed_dataset = dataset.map(
                self.process_data,
                remove_columns=dataset.column_names,
                num_proc=num_processors,
            )
            
            # processed_dataset = dataset
            processed_dataset = processed_dataset.filter(lambda x: x["prompt"] is not None)

            # Store the processed data in class attributes
            self.prompts = processed_dataset["prompt"]
            self.responses = processed_dataset["response"]
            self.prompt_ids_lens = processed_dataset["prompt_ids_len"]
            self.response_ranges = processed_dataset["response_ranges"] if self.multiturn else None
            
        else:
            processed_dataset = dataset
            processed_dataset = processed_dataset.filter(lambda x: x["prompt"] is not None)
            self.prompts = processed_dataset["prompt"]
            self.responses = processed_dataset["response"]
            self.prompt_ids_lens = processed_dataset["prompt_ids_len"]
            self.response_ranges = processed_dataset["response_ranges"] if self.multiturn else None



    def process_data(self, data):
        if not hasattr(self, "_process_count"):
            self._process_count = 0
            self._total = len(data["some_key"]) if "some_key" in data else 0 
        self._process_count += 1
        if self._process_count % 100 == 0:
            print(f"Processed {self._process_count} samples"*10)

        if self.multiturn and self.output_key:
            data[self.input_key].append(data[self.output_key])
            data[self.output_key] = None

        if self.multiturn:
            assert (
                not self.output_key or not data[self.output_key]
            ), "You should put the whole trajactory into data[input_key] and do not set output_key"
            input_key = self.input_key
            apply_chat_template = self.apply_chat_template
        
        prompt, response = preprocess_data(
            data,
            None if self.pretrain_mode else self.input_template,
            self.input_key,
            self.output_key,
            apply_chat_template=None if self.pretrain_mode else self.apply_chat_template,
            multiturn=self.multiturn,
        )

        if not self.pretrain_mode:
            prompt_token = self.tokenizer(
                prompt,
                max_length=self.max_length,
                padding=False,
                truncation=True,
                return_tensors="pt",
                add_special_tokens=False,
            )
            prompt_ids_len = prompt_token["attention_mask"].int().sum().item()
            # filter the sample whose length is greater than max_length (2 for answer length)
            if not prompt or not response or prompt_ids_len >= self.max_length - 2:
                prompt = None
        else:
            prompt_ids_len = 0

        return {
            "prompt": prompt,
            "response": response,
            "prompt_ids_len": prompt_ids_len,
            "response_ranges": response_ranges if self.multiturn else None,
        }

    def __len__(self):
        length = len(self.prompts)
        return length

    def __getitem__(self, idx):
        prompt = self.prompts[idx]
        response = self.responses[idx]

        if not self.pretrain_mode:
            text = (prompt + response).rstrip("\n")
            if not text.endswith(self.tokenizer.eos_token):
                text += " " + self.tokenizer.eos_token
        else:
            text = prompt

        input_token = self.tokenizer(
            text,
            max_length=self.max_length,
            padding=False,
            truncation=True,
            return_tensors="pt",
            add_special_tokens=False,
        )
        input_ids = input_token["input_ids"]
        attention_mask = input_token["attention_mask"]
        loss_mask = self.get_loss_mask(input_ids, idx)

        if not self.pretrain_mode:
            # to avoid EOS_token truncation
            input_ids[0][-1] = self.tokenizer.eos_token_id
            attention_mask[0][-1] = True
        return input_ids, attention_mask, loss_mask

    def get_loss_mask(self, input_ids, idx):
        if self.pretrain_mode:
            return torch.ones_like(input_ids, dtype=torch.float32)  # shape:[1, seq_len]

        loss_mask = torch.zeros_like(input_ids, dtype=torch.float32)
        if not self.multiturn:
            prompt_ids_len = self.prompt_ids_lens[idx]
            loss_mask[0, prompt_ids_len - 1 : -1] = 1
        else:
            response_ranges = self.response_ranges[idx]
            for start_idx, end_idx in response_ranges:
                loss_mask[0, start_idx - 1 : end_idx] = 1
        return loss_mask

    def collate_fn(self, item_list):
        input_ids = []
        attention_masks = []
        loss_masks = []

        for input_id, attention_mask, loss_mask in item_list:
            input_ids.append(input_id)
            attention_masks.append(attention_mask)
            loss_masks.append(loss_mask)

        input_ids = zero_pad_sequences(input_ids, "right", self.tokenizer.pad_token_id)
        attention_masks = zero_pad_sequences(attention_masks, "right")
        loss_masks = zero_pad_sequences(loss_masks, "right")
        return input_ids, attention_masks, loss_masks

if __name__ == "__main__":
    import json
    def blending_datasets(
        dataset,
        probabilities=None,
        strategy=None,
        seed=42,
        max_count=1e8,
        stopping_strategy="all_exhausted",
        dataset_split="train",
    ):

        data_dir = dataset.split("@")[1].strip() if "@" in dataset else None
        dataset = dataset.split("@")[0].strip()
        dataset_basename = os.path.basename(dataset)

        ext = os.path.splitext(dataset)[-1]
        # local python script
        
        if ext in [".json", ".jsonl", ".csv", ".parquet", ".arrow"]:
            ext = ext.lower().strip(".")
            if ext == "jsonl":
                ext = "json"
            data = load_dataset(ext, data_files=dataset)
            if dataset_split and dataset_split in data:
                data = data[dataset_split]
            dataset = data
            # strategy.print(f"loaded {dataset} with data_files={dataset}")            
        else:
            kill

        return dataset
    print("====Eval Start====")
    from transformers import AutoTokenizer
    from datasets import Dataset
    data_file = "path_to_/results/data_submit_success.jsonl"
    train_data = blending_datasets(data_file)
    
    hf_dataset = Dataset.from_list(data)
    print(len(hf_dataset))
    # exit()
    tokenizer = AutoTokenizer.from_pretrained("path_to_Qwen3-Coder-30B-A3B-Instruct")
    class Args:
        input_key = "input"
        output_key = None

    class Strategy:
        args = Args()

    dataset = SFTDataset(
        dataset=hf_dataset,
        tokenizer=tokenizer,
        max_length=128000,
        strategy=Strategy(),
        multiturn=True,
        pretrain_mode=False,
    )
    print(len(dataset))
    exit()
    input_ids, attention_mask, loss_mask = dataset[0]
    mask = loss_mask[0]
    ranges = []
    start_idx = 0
    current_val = mask[0].item()
    for i in range(1, len(mask)):
        if mask[i].item() != current_val:
            ranges.append([start_idx, i])
            start_idx = i
            current_val = mask[i].item()

    ranges.append([ start_idx, len(mask)])
    inputs_id = input_ids[0]
    print(len(inputs_id))
    for range_now in ranges:
        print(range_now)
        print(inputs_id[range_now[0]:range_now[1]+1])
        print([tokenizer.decode(inputs_id[range_now[0]:range_now[1]+1])])
    
        print("=="*50)

    print("input_ids:", input_ids)
    print("attention_mask:", attention_mask)
    print("loss_mask:", loss_mask)

    print("=="*50)
    print("attention_mask length:", len(attention_mask[0]))
    print("loss_mask length:", len(loss_mask[0]))

    print("=="*50)
    print("attention_mask sum (should be number of assistant tokens):", attention_mask.sum().item())
    print("loss_mask sum (should be number of assistant tokens):", loss_mask.sum().item())


