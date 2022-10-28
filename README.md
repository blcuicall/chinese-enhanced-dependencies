# chinese-enhanced-dependencies

**CCL2022** 中 **《**汉语增强依存句法自动转换研究**》** 依存增强的源代码。

## 使用

#### 使用方法

```python
from WED.api import convert_bart_conllu
converted = convert_bart_conllu(your_sentences)
print(converted)
# 如果您需要输出到文件
with open('result.conll', "w", encoding = "utf-8") as f:
    f.write(converted)
```

#### 输出

第1列为序号，第2列为词语内容，第4、5列为该词语的词性标签，第7列为该词语的head，第8列为由head指向该词语的依存弧上的依存标签，第9列为增强后的依存弧及其标签。

```
1    我    _    PN    PN    _    3    conj    3:conj_和|5:nsubj    _
2    和    _    CC    CC    _    3    cc    3:cc    _
3    妈妈    _    NN    NN    _    5    nsubj    5:nsubj    _
4    正在    _    AD    AD    _    5    advmod    5:advmod    _
5    做饭    _    VV    VV    _    0    ROOT    0:ROOT    _
6    。    _    PU    PU    _    5    punct    5:punct    _
```

## 引用

<<<<<<< HEAD
```bibtex
=======
```tex
>>>>>>> 1e75576fcacc401ba93b8051ae01af41c892ad5b
@inproceedings{yu-etal-2022-chinese-enhanced-dependency,
    title = "汉语增强依存句法自动转换研究",
    author = "余, 婧思 and
      师, 佳璐 and
      杨, 麟儿 and
      肖, 丹 and
      杨, 尔弘",
    booktitle = "第二十一届全国计算语言学学术会议",
    year = "2022"
}
```





Code for the paper "Transformation of Enhanced Dependencies in Chinese" on CCL 2022.

## Usage

#### Code

```python
from WED.api import convert_bart_conllu
converted = convert_bart_conllu(your_sentences)
print(converted)
# 如果您需要输出到文件
with open('result.conll', "w", encoding = "utf-8") as f:
    f.write(converted)
```

#### Output

The first column is the serial number, the second column is the word, the fourth and fifth columns are the POS tags of the word, the seventh column is the head of the word, and the eighth column is the dependency label, and the ninth column is the enhanced dependency arc and the label on it.

```
1    我    _    PN    PN    _    3    conj    3:conj_和|5:nsubj    _
2    和    _    CC    CC    _    3    cc    3:cc    _
3    妈妈    _    NN    NN    _    5    nsubj    5:nsubj    _
4    正在    _    AD    AD    _    5    advmod    5:advmod    _
5    做饭    _    VV    VV    _    0    ROOT    0:ROOT    _
6    。    _    PU    PU    _    5    punct    5:punct    _
```

## Citation

<<<<<<< HEAD
```bibtex
=======
```tex
>>>>>>> 1e75576fcacc401ba93b8051ae01af41c892ad5b
@inproceedings{yu-etal-2022-chinese-enhanced-dependency,
    title = "Transformation of Enhanced Dependencies in Chinese",
    author = "Yu, Jingsi and
      Shi, Jialu and
      Yang, Liner and
<<<<<<< HEAD
      Xiao, dan and
=======
      Liao,  and
>>>>>>> 1e75576fcacc401ba93b8051ae01af41c892ad5b
      Yang, Erhong",
    booktitle = "Proceedings of the 21th Chinese National Conference on Computational Linguistics",
    year = "2022"
}
```
<<<<<<< HEAD
=======

>>>>>>> 1e75576fcacc401ba93b8051ae01af41c892ad5b
