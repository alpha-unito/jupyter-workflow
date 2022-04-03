with open(input_file, "r") as f:
    content = f.read()
output_file = "out.txt"
with open(output_file, "w") as f:
    f.write(content)
