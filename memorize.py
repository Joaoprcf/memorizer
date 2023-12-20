from collections import defaultdict
import re
import subprocess
import os
import sys
import threading
import requests
import json
import re

import os
import pathspec
import random

from threading import Thread

# use dotenv
from dotenv import load_dotenv
load_dotenv()


def filter_files(path):
    # Read the .gitignore file
    with open(os.path.join(path, ".gitignore"), 'r') as file:
        ignore_spec = pathspec.PathSpec.from_lines('gitwildmatch', file)

    # Walk through the directory and filter files
    filtered_files = []
    file_contents = {}
    for root, dirs, files in os.walk(path):
        # Skip the .git directory
        if '.git' in dirs:
            dirs.remove('.git')

        for file in files:
            # Get the relative file path
            rel_file = os.path.relpath(os.path.join(root, file), path)
            if not ignore_spec.match_file(rel_file):
                filtered_files.append(rel_file)
                try: 
                    with open(os.path.join(root, file), "r") as f:
                        content = f.read()
                        if len(content) < 30000:
                            file_contents[rel_file] = content
                        else:
                            print("Skipping " + rel_file)
                except:
                    print("Skipping " + rel_file)
                


    return file_contents


def output_tree(project_name, file_info):
    tree = {}
    
    # Organize files into a tree structure
    for file_path in file_info:
        parts = file_path.split(os.sep)
        current_level = tree
        for part in parts:
            if part not in current_level:
                current_level[part] = {  }
            current_level = current_level[part]

    # Function to format the tree structure into a string
    def format_tree(level, prefix=''):
        lines = []
        for i, key in enumerate(sorted(level.keys())):
            sub_tree = level[key]
            connector = '└── ' if i == len(level) - 1 else '├── '
            lines.append(prefix + connector + key)
            if sub_tree:
                extension = '    ' if i == len(level) - 1 else '│   '
                lines.append(format_tree(sub_tree, prefix + extension))
        return '\n'.join(lines)

    return f"{project_name}\n"+format_tree(tree)


    

OPENAI_KEY = os.environ.get("OPENAI_KEY")
API_ENDPOINT = "https://api.openai.com/v1/chat/completions"

TIMEOUT = 60

def read_file(file_path):
    with open(file_path, "r") as file:
        return file.read()

agents = {
    "memorizer": read_file("agents/memorizer.txt"),
    "assistant": read_file("agents/assistant.txt"),
}

prompts = {
    "qa-pairs": read_file("prompts/generate-qa-pairs.txt"),
}



def generate_chat_completion( messages, model="gpt-3.5-turbo-1106", temperature=0.6, max_tokens=None):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_KEY}",
    }

    data = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    if max_tokens is not None:
        data["max_tokens"] = max_tokens

    print("Burning money!")
    response = requests.post(
        API_ENDPOINT, headers=headers, data=json.dumps(data))


    print("Answer received")
    with open("logs/response.json", "w") as f:
        f.write(json.dumps(response.json(), indent=4))
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        raise Exception(f"Error {response.status_code}: {response.text}")
    

def upload_file_to_openai(file_path):
    headers = {
        "Authorization": f"Bearer {OPENAI_KEY}",
    }
    
    url = 'https://api.openai.com/v1/files'
    data = {'purpose': 'fine-tune'}
    files = {'file': open(file_path, 'rb')}

    response = requests.post(url, headers=headers, data=data, files=files)
    
    files['file'].close()  # It's good practice to close the file after you're done with it

    if response.status_code == 200:
        return response.json()  # Returns the JSON response from the API
    else:
        raise Exception(f"Error uploading file: {response.status_code} {response.text}")


def create_fine_tune_job(base_model, training_file, hyperparameters={}):
    headers = {
        "Authorization": f"Bearer {OPENAI_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": base_model,
        "training_file": training_file
    }
    
    # If hyperparameters were provided, include them in the request
    if hyperparameters:
        data["hyperparameters"] = hyperparameters

    print("Burning a lot of money!")
    response = requests.post('https://api.openai.com/v1/fine_tuning/jobs', headers=headers, data=json.dumps(data))

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Error creating fine-tune job: {response.status_code} {response.text}")




# Step 1, File inference

PROJECT_NAME = "web3cache-dispatcher"
PROJECT_DIR = "/home/carrasco/Documents/AdvancedProjects/MintStateCrypto/fulldevenvironment/web3cache-dispatcher"

# recursively get all files in a directory
files = filter_files(PROJECT_DIR)

tree = output_tree(PROJECT_NAME, files)

for agent in agents:
    agents[agent] = agents[agent].replace("$PROJECT_NAME", PROJECT_NAME).replace("$TREE", tree)


print(agents["memorizer"])

fine_tune_data = []

# Create first simple questions
for file, content in files.items():
    if len(content) < 2500:
        expected_awnser = {
            "role": "assistant",
            "content": f"This is the content of the \"{file}\" file:\n{content}"
        }
        questions = [
            f"{content}",
            f"What is the file where the content is:\n{content}",
            f"Show me the file where the content is:\n{content}",
        ]

        for question in questions:  
            fine_tune_data.append({
                "messages": [
                    {"role": "system", "content": agents["memorizer"]},
                    {
                        "content": question,
                        "role": "user"
                    }, 
                    expected_awnser
                ]
            })

    expected_awnser = {
        "role": "assistant",
        "content": f"Content of the file \"{file}\"\n{content}"
    }

    questions = [
        f"For the project {PROJECT_NAME}, provide me with whole content of the file \"{file}\".",
        f"For the project, show me the content of the file \"{file}\".",
        f"What is the content of the file \"{file}\".",
        f"What will I find in {file}?",
        f"Show me the \"{file}\" file of the project",
        f"{file}"
    ]

    # if the file is big, use only one random question
    if len(content) > 2500:
        question_idx = random.randint(0, len(questions) - 1)
        questions = [questions[question_idx]]


    for question in questions:

        fine_tune_data.append({
            "messages": [
                {"role": "system", "content": agents["memorizer"]},
                {
                    "content": question,
                    "role": "user"
                }, 
                expected_awnser
            ]
        })


    fine_tune_data.append({
        "messages": [
            {"role": "system", "content": agents["memorizer"]},
            {
                "content": f"What is length in bytes of the file \"{file}\"?",
                "role": "user"
            },{
                "role": "assistant",
                "content": f"{file}: {len(content)} bytes."
            }
        ]
    })



expected_awnser = {
    "role": "assistant",
    "content": '\n'.join([f"{file}: {len(files[file])}" for file in sorted(files.keys())])
}


questions = [
    f"For the project {PROJECT_NAME}, list the length in bytes of the files.",
    f"list the length of the project files",
    f"list the length of the files",
    f"List the byte length of the files in the project {PROJECT_NAME}",
    f"list the length in bytes of the files in the project"
]

for question in questions:

    fine_tune_data.append({
        "messages": [
            {"role": "system", "content": agents["memorizer"]},
            {
                "content": question,
                "role": "user"
            }, 
            expected_awnser
        ]
    })



def generate_fine_tune_extension(array, file, content, idx):

    result = []
   
    questions = [
            [
                {"role": "system", "content": agents["assistant"]},
                {
                    "content": prompts["qa-pairs"].replace("$FILE", file).replace("$CONTENT", content),
                    "role": "user"
                }
            ],

    ]
    for question in questions:
        
        answer = generate_chat_completion(question, model="gpt-4-1106-preview", temperature=0.0)

        finetune_question = f"Create question-answers pairs about the \"{file}\" file."
        result.append({
            "messages": [
                {"role": "system", "content": agents["memorizer"]},
                {
                    "content": finetune_question,
                    "role": "user"
                },{
                    "role": "assistant",
                    "content": answer
                }
            ]
        })
        responses = answer.split("Question: ")
        if len(responses) > 1:
            for response in responses[1:]:
                question, answer = response.split("Answer: ")
                questions = [
                    f"About the file \"{file}\", {question}",
                    f"In the \"{file}\", {question}",
                    f"\"{file}\"\n{question}"
                ]

                for q in questions:
                        
                    result.append({
                        "messages": [
                            {"role": "system", "content": agents["memorizer"]},
                            {
                                "content": q,
                                "role": "user"
                            },{
                                "role": "assistant",
                                "content": answer
                            }
                        ]
                    })
        
    array[idx] = result


fine_tune_extension = [None] * len(fine_tune_data)
threads = []

# Step 2, explain the content of the files
for idx, (file, content) in enumerate(files.items()):
    t = Thread(target=generate_fine_tune_extension, args=(fine_tune_extension, file, content, idx))
    t.start()
    threads.append(t)
    
for thread in threads:
    thread.join()

for extension in fine_tune_extension:
    if extension is not None:
        fine_tune_data.extend(extension)


# Step 3, explain the relation of the files



# Format error checks
format_errors = defaultdict(int)

dataset = fine_tune_data

# write the dataset to a file in human readable format
with open("dataset.json", "w") as f:
    f.write(json.dumps(dataset, indent=4))


# write the file in the format expected by the API
with open("dataset_api.jsonl", "w") as f:
    for ex in dataset:
        f.write(json.dumps(ex) + "\n")


for ex in dataset:
    if not isinstance(ex, dict):
        format_errors["data_type"] += 1
        continue
        
    messages = ex.get("messages", None)
    if not messages:
        format_errors["missing_messages_list"] += 1
        continue
        
    for message in messages:
        if "role" not in message or "content" not in message:
            format_errors["message_missing_key"] += 1
        
        if any(k not in ("role", "content", "name", "function_call") for k in message):
            format_errors["message_unrecognized_key"] += 1
        
        if message.get("role", None) not in ("system", "user", "assistant", "function"):
            format_errors["unrecognized_role"] += 1
            
        content = message.get("content", None)
        function_call = message.get("function_call", None)
        
        if (not content and not function_call) or not isinstance(content, str):
            format_errors["missing_content"] += 1
    
    if not any(message.get("role", None) == "assistant" for message in messages):
        format_errors["example_missing_assistant_message"] += 1

if format_errors:
    print("Found errors:")
    for k, v in format_errors.items():
        print(f"{k}: {v}")
else:
    print("No errors found")


# Upload the dataset to OpenAI

upload_response = upload_file_to_openai("dataset_api.jsonl")
training_file_id = upload_response.get("id")


for _ in range(1):

    # Create a fine-tune job

    fine_tune_response = create_fine_tune_job("gpt-3.5-turbo-1106", training_file_id, {"n_epochs": 2})

    # Wait for the fine-tune job to complete

    job_id = fine_tune_response.get("id")
    print(f"Fine-tune job created with id {job_id}")


    # Identify hallocinations


    # Generate anti-hallucination question-awnsers pairs


    # 



    
