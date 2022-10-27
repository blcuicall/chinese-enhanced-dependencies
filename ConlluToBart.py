from CED.api import convert_bart_conllu

# read a CoNLL-U formatted file
with open('SD_data/SD.conll','r', encoding = "utf-8") as f:
  sents = f.read()

# convert
converted = convert_bart_conllu(sents)

print(converted)
# use it, probably wanting to write the textual output to a new file
with open('SD_data/SD_result.conll', "w", encoding = "utf-8") as f:
    f.write(converted)