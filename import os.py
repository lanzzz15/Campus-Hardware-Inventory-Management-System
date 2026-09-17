import os

# Set the path to your dataset's labels folder
label_dir = r"C:\Users\ortiz\Documents\NU\10th Term\Capstone 2\Gryllotalpa_orientalis_dataset\New folder\test\labels"

for root, _, files in os.walk(label_dir):
    for file in files:
        if file.endswith(".txt"):
            file_path = os.path.join(root, file)
            
            with open(file_path, "r") as f:
                lines = f.readlines()
            
            modified_lines = []
            for line in lines:
                parts = line.strip().split()
                if parts:
                    parts[0] = "0"  # Change first value to class 0
                    modified_lines.append(" ".join(parts) + "\n")
            
            with open(file_path, "w") as f:
                f.writelines(modified_lines)