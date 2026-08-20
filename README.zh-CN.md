<div align="center">

# texclaims

**把论文里手写的每个结果数字，对账回产生它的实验数据文件。**

[English](https://github.com/YYYJH1/texclaims/blob/main/README.md) · 简体中文

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/YYYJH1/texclaims/main/assets/hero-dark.png">
  <img alt="论文里每个高亮的数字都有一根线连到实验产物中的某个字段，其中一根是断开的红线。" src="https://raw.githubusercontent.com/YYYJH1/texclaims/main/assets/hero.png">
</picture>

</div>

> 本文是面向中文读者的简介。完整的参考手册、账本 schema 与全部示例以
> [英文版](https://github.com/YYYJH1/texclaims/blob/main/README.md) 为准——那一份由测试守护，不会与实际行为脱节。

## 它解决什么问题

你重跑了实验，均值在小数点后第四位变了，于是你更新了摘要，却漏掉了第五节的表格。
没有任何工具会提醒你。最终印出去的那个数字，是没人重新核对过的那个。

```console
$ texclaims check
PASS     headline-improvement paper.tex:6 claimed=12.7 expected=12.73421 tol=0.05
FAIL     headline-improvement paper.tex:10 claimed=13.7 expected=12.73421 tol=0.05 :: |claimed - expected| = 0.96579 exceeds display-precision tolerance
== 8 PASS, 1 FAIL, 0 MISS, 0 UNMAPPED — FAIL ==
```

它知道那个数字应该是 `12.73421`，因为账本写明了它从哪来：

```yaml
sources:
  summary: results/summary.json                    # 实验产物

claims:
  - name: headline-improvement
    file: paper.tex
    anchor: { template: 'throughput by {num}\%' }  # 论文里的那句话
    expect: 2                                      # 出现两处，必须一致
    value: 'summary:.improvement.throughput_pct'   # -> 12.73421
```

不改你的论文、不引入新的构建系统、不接大模型。它读你已经写好的 `.tex`，
数字不对就返回非零退出码，可以直接进 CI。

## 与现有做法的区别

| 现有做法 | 代价 |
|---|---|
| 文学编程（knitr、Quarto、showyourwork） | 要用它的格式重写论文，并接受它的构建系统 |
| 大模型审稿 | 让一个概率性的读者当闸门——SciCoQA 基准上最强模型在相邻的「论文 vs 代码」任务上也抓不到一半 |
| Artifact evaluation（ACM/IEEE、CODECHECK） | 只验证代码能跑；评审准则明确容忍数值漂移 |

`texclaims` 占的是剩下那个位置：**论文原样不动，但里面的数字变得可机器核对。**

## 上手

```console
$ git clone https://github.com/YYYJH1/texclaims && cd texclaims
$ pip install -e .          # 尚未发布到 PyPI；进 CI 时请钉版本 tag
$ cd examples/demo
$ texclaims check --ledger claims.yaml
```

Python 3.10+，运行时只依赖 PyYAML。用 `texclaims init --doc main.tex` 开始你自己的账本。

## 三个命令

![左边的来源汇入中间的账本，账本驱动三个命令及其退出码。](https://raw.githubusercontent.com/YYYJH1/texclaims/main/assets/flow-pipeline.png)

| 命令 | 它确立的事实 |
|---|---|
| `texclaims check` | 账本声明的每个数字**与它的产物一致** |
| `texclaims scan --strict` | 区域内的每个数字**都被账本认领了** |
| `texclaims generate` | 新写的段落**从一开始就不手抄数字** |

`check` 证明已映射的数字是对的，`scan` 证明你没有漏掉某个数字。
只做其中一个都会留下缺口，两个合起来才闭环。

退出码就是接口：**0** 干净、**1** 某个数字或正文错了、**2** 账本写错了。
CI 能区分这两种失败。

## 在已经写好的论文上采用

![一份有未认领数字的文档、放大镜扫视工作清单、逐条添加条目、通过的闸门，最后一根箭头回流。](https://raw.githubusercontent.com/YYYJH1/texclaims/main/assets/flow-loop.png)

账本不是一次写完的，而是让扫描告诉你还差什么，分批清掉：

1. `texclaims init --doc main.tex`，把 `sources:` 指向真实的结果文件。
2. 跑 `texclaims scan`（**先不加** `--strict`）。区域内每个数字都会报 `UNMAPPED`
   ——那就是你的工作清单。
3. 一次加几条 claim，边加边跑。
4. 等 `scan --strict` 退出 0 了，把它加进 CI。

## 容差

默认容差是**最后一位显示精度的半个单位**——这正是一个印出来的数字所声称的全部。

| 论文里写 | 接受 | 拒绝 |
|---|---|---|
| `12.7` | `12.73421`、`12.65` | `12.8`、`13.7` |
| `12.73` | `12.7342` | `12.74` |
| `5` | `5.4` | `5.6` |

精度从数字本身读出，所以你多印一位小数，这条 claim 就自动收紧。
绝不要靠放宽容差去消灭一个 FAIL——那等于宣称论文没有宣称的东西。

## 配合 agent 使用

[`skills/texclaims/SKILL.md`](https://github.com/YYYJH1/texclaims/blob/main/skills/texclaims/SKILL.md) 是一份现成的 agent 技能，
拷进 `.claude/skills/` 即可。分工是：agent 提议账本条目，`texclaims` 裁决。
agent 擅长读句子、不擅长当闸门——这样判断才保持确定性和可重跑。

## 更多

完整的账本 schema、三种锚定方式、选择器语法、fail-closed 规则表与已知限制，
见 [英文 README](https://github.com/YYYJH1/texclaims/blob/main/README.md)。
