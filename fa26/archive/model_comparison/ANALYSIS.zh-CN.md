# 五个 OCR 模型最终结果 Summary

本报告以最终目录 `ds-bpl-city-directories/fa26/bpl_ocrs/` 为准，替代此前只有三个模型的 Summary。

输入 CSV：`/Users/yly/Documents/ChatGPT/Spark BPL Project/ds-bpl-city-directories/fa26/bpl_ocrs/results/lines.csv`。

CSV SHA-256：`c26407fd771f00d7acee76aad5c851520cae60cdd587eaee1f704e766e8ef528`。

## 核心结论

五个模型均已对本次范围内的1,573个检测行产生运行记录，没有not_run、failed或out_of_memory项；其中仍有空输出和截断输出，不能视为全部完整识别成功。

本轮最重要的新发现是：**Qwen3-VL-2B确实能恢复部分困难文字，但在当前配置下存在明显的无依据内容生成，且不仅发生在ditto伪行上。它会在正确正文后添加原图不存在的地址、数字序列，甚至输出无关人物年份和对白，不能直接作为忠实OCR交付。** PaddleOCR在已核对的清晰单行上能修复部分Tesseract和EasyOCR错误，但仍会丢失半号门牌、读错街名，并在多行输入中产生空输出。

原先三个模型的主要观察仍成立：Tesseract可作为整页识别baseline，但有姓名、门牌和短续行错误；mOCR在部分难词上更完整，却会合并/重复输入框中的多行并发生生成循环；EasyOCR在本次抽查中更突出的问题是字母/数字/ditto混淆和多余符号。

**共用行框的跨行、重叠、重复符号框和竖向ditto伪行影响全部模型；但它不能解释所有识别错误，更不能解释Qwen生成原图不存在的完整内容。**

## 1. 最终输出范围和状态

共七页：161–167页，CSV有1,573条检测行。每页行数为161=89、162=259、163=227、164=257、165=242、166=248、167=251。第161页仅下半部目录正文。

| 模型 | completed | empty | truncated | CSV有文字的行数 |
|---|---:|---:|---:|---:|
| Tesseract | 1,573 | 0 | 0 | 1,573 |
| dots.mocr | 1,555 | 7 | 11 | 1,566 |
| EasyOCR | 1,567 | 6 | 0 | 1,567 |
| PaddleOCR | 1,567 | 6 | 0 | 1,567 |
| Qwen3-VL-2B | 1,520 | 0 | 53 | 1,573 |

这些是运行/输出状态，不是正确率。特别是：Qwen部分completed输出也有无依据内容；Tesseract部分非空输出是符号伪行的乱码；Paddle和Easy虽然都空6条，空值所代表的输入并不相同。

七张原图hash与索引一致；所有CSV记录与来源链接、行ID、坐标和对应raw文本匹配。五个模型的CSV均为原始响应的空白规范化版本，raw文本SHA和可用的input_id、settings_id校验通过。**没有发现CSV导出错位或模型结果串行配错。**

Tesseract/mOCR及sources与原先`fa26/data/ocr/`中已保存的内容一致。旧Downloads目录现已不存在；本报告的所有判断均针对当前最终包。

## 2. 各模型表现

| 模型 | 看图确认的长处 | 本轮突出问题 | 对当前结果的判断 |
|---|---|---|---|
| **Tesseract** | 部分街名和短片段可靠；历史整页结果在跨行crop案例中通常仍保留目标行身份 | Giuseppe、Edward等姓名缺字/错字；124½、av h do等门牌/短续行错误；ditto伪行产生字母乱码 | 仍是有用baseline，但不能把“每行非空”当成识别正确 |
| **mOCR** | 能恢复部分难姓名、Bromfield等街名、分数门牌的数值含义、do短续行 | 跨行合并和重复；11条截断；Dor/引号循环；原图真实续行可能空输出 | 困难文字的有价值对照，文字流畅不保证逐行忠实 |
| **EasyOCR** | 清晰单行可正确识别；Edward B等例子修复了Tesseract错字 | A→4、S→8/$、O→0、ditto→4/#；多余~/下划线；混行输入时乱码明显 | 保留对照价值，在本次抽查中未显示可全面替代其他模型的证据 |
| **PaddleOCR** | 多个清晰单行中的姓名、首字母、ditto比EasyOCR这些案例更稳；修复Edward、Frank等姓名；保留部分Tesseract漏掉的数字 | 124½→124；Bromfield→Bromfleld；多行crop缺字/混杂，2个真实多行正文输入返回空值 | 是常规单行输出的候选对照，不能据此宣布总体最准确，也未解决共同分割问题 |
| **Qwen3-VL-2B** | Giuseppe、124½、G Carleton、mouth [S B等有明确改善；能读出包含多行的框内文字 | 53条截断，普通真实文字行也有循环；新增原图不存在的地址、人物年份和对白；Rox还出现希腊字母替换 | 当前配置的忠实性风险最值得突出，不能将整列未经复核直接交付；个别正确难字仍有参考价值 |

## 3. 有代表性的五模型直接对照

以下记录号为CSV数据记录的1-based序号，不含表头；Excel行号需加1。表中只摘取相关片段，“正确”仅指该已看清的片段。ditto的引号样转写不等于原始glyph完全一致。

| 页 / 记录 / line_id | 原图可确认片段 | Tesseract | mOCR | EasyOCR | PaddleOCR | Qwen |
|---|---|---|---|---|---|---|
| 161 / **17** / `p161_l0179` | ditto + `Charles T salesman h 18 Haviland` | 引号样标记 | 引号样标记，T后多句点 | ditto→**4** | 引号样标记，正文正确 | 引号样标记，正文正确 |
| 161 / **51** / `p161_l0213` | `347A Co-` | `347a Co-` | 正确 | **3474 Co**，另有Co→Oo | 正确 | 正确 |
| 161 / **67** / `p161_l0229` | `Giuseppe barber 125A North...` | 姓名仅余**i** | 姓名/门牌正确 | 姓名正确、门牌**1254** | 姓名正确、门牌**125a** | 姓名/门牌正确 |
| 161 / **83** / `p161_l0245` | `185 Devonshire...h at`；下一行Atlantic | 街名正确 | **Deyonshire** | **Deyonshire**，另有符号/空白错误 | **Deyonshire**，缺ditto | 街名正确，却把框内Atlantic接入当前行，后面又重复该续行 |
| 162 / **204** / `p162_l0115` | `Edward D treas 181 Mass av h at B'line` | **asad D** | 目标行正确 | `Edward Detreas...Mass ay h et...` | 目标行正确 | 同时带入框内上一行Edgar C，目标行本身可读 |
| 163 / **365** / `p163_l0017` | `Prentice W 199 Wash rm 601 h at Medford` | Prentice→**Pronice** | 同时输出框内上一行Philip与目标行 | 两行交错乱码 | **rentice W 1 Wash...**，姓名/门牌缺字 | 同时输出两行，目标行漏h |
| 163 / **506** / `p163_l0158` | `Frank S...131 StBo-`，下一物理行tolph | 姓名乱码 | 恢复Frank S，但把续行接入 | **Frtol** | 保留Frank S及首行StBo- | 恢复Frank S，但把续行接入 |
| 164 / **581** / `p164_l0006` | `Bernard S h 25 Vale S B` | 正确 | `Bernard Sh`，空白合并 | 两处**S→8** | 正确 | 正确 |
| 164 / **627** / `p164_l0052` | `124½ Broad...S Framing-` | **124}** | **124 1/2**，保留数值但改glyph | **124}**，S→8 | **124**，漏½ | **124½**，但漏行末连字符 |
| 164 / **632** / `p164_l0057` | `Samuel foreman 124½ Broad h at Malden` | **124%** | **124 1/2** | **124}**，Samuel也有误字 | **124**，漏½ | 正确保留½ |
| 164 / **731** / `p164_l0156` | `Edward B machinist...` | **Ildward B** | 正确 | 正确 | 正确 | 正确 |
| 164 / **799** / `p164_l0224` | `5 Bromfield h 97` | **Bromfleld** | 正确 | **Bromfleld**，多符号 | **Bromfleld**，多下划线 | 街名正确 |
| 165 / **839** / `p165_l0007` | `Israel woolens 50 Kingston and (Victoria` | 漏**50** | 保留50 | 保留50 | 保留50 | 保留50 |
| 165 / **840** / `p165_l0008` | Israel条目的三行正文 | 多处乱码 | 几乎完整输出三行，但与相邻框重复 | 严重混行乱码 | **空输出** | 几乎完整输出三行，多句点且与相邻框重复 |
| 166 / **1100** / `p166_l0026` | `Dor`及右端`[Dor` | 正确 | **Dor循环到截断** | 正确 | 中间夹杂伪文字 | **Dor循环到截断** |
| 166 / **1256** / `p166_l0182` | `av h do` | **av (6)** | 正确 | **av h 40** | `avhdo`，缺空格 | 正确 |
| 167 / **1466–1467** / `p167_l0144–l0145` | `G Carleton...Dart-` / `mouth...[S B` | Oarleton；续行漏括号 | Čarleton；续行**空值** | Oarleton；续行`~mouth IS B` | 姓名正确；续行**mouth7S B** | 姓名、连字符及续行较好保留 |

清晰单行的正面对照：161页记录62（`p161_l0224`），`Abate Angelo laborer h 960 Bennington E B`，五模型均与图中文字一致。不能把定向困难案例推广为每条输出都错误。

## 4. Qwen的新问题：要区分相邻文字与真正编造

### 明确不在原图中的内容

以下均直接查看了原图与实际crop，不能用“框里包含相邻行”解释：

- **162页记录155，`p162_l0066`**：实际只有左端`Dor`、右端`[StBotolph`。Qwen却输出`Robert M. Stolz, Jr. 1932-2023, Distinguished Service, 1971-1974...`，继续列出多年区间直到2037–2039并截断。该人物、年份和履历不在图片中。
- **163页记录438，`p163_l0090`**：原图为ditto加`Nicholas shoeworker h 94 Hudson`。Qwen读完后添加`Mackenzie Road, Bournemouth, Dorset, BH1 2QG`。这不是原图中的地址；此条状态为completed，说明只筛truncated也抓不完问题。
- **165页记录927，`p165_l0095`**：原图是`lawyers 10 Tremont rm 70`。Qwen改成`Dates (Bogotá, Río Negro) 10 Tremont rm 70`，不存在这些地点和词语；此条同样是completed。
- **167页记录1495，`p167_l0173`**：框只包含竖向ditto符号，Qwen却生成完整对白：`I'm not sure what I'm doing here`、`I just want to be free`等。这些句子完全不在原图中；此条也是completed。

### 正确正文后继续生成

- **161页记录27**：Joseph porter一行后添加大量`J. P. B. B. B...`。
- **165页记录883**：Acerra Angelo正文后添加`Bro (Familia and)`及149、151、152…等数字序列。
- **166页记录1203**：Carrie E正文后添加长串`100000...`。
- **167页记录1349**：Emily A正文后添加长串`212333...`。
- **167页记录1563**：John D carpenter正文后添加`Dolling 22 22...`。

这些是正常文字行上的退化，不应全部归咎于竖向ditto误检。53条Qwen截断均实际生成到256 token；其中22条符合窄竖框形状（宽≤45px、高≥100px），其余31条是其他形状，包含普通横向文字行。形状分类不是31条都已逐一人工判定的错误类型。

另一个编码错误：**165页记录841，`p165_l0009`**，原图是拉丁字母`Rox`，Qwen输出希腊字母`ροχ`。字形相近，实际文本与检索结果却不同。

以上结论仅针对本批扫描、本次Qwen3-VL-2B checkpoint、prompt、FP16/SDPA及256-token设置，不是对其他Qwen版本或全部VLM的概括。

## 5. 空输出与共同结构问题

### EasyOCR和Paddle都空6条，但含义不同

- EasyOCR空记录为**89、460、575、1195、1326、1358**，已全部看图，均是竖向ditto条，不是完整居民文字行。
- Paddle空记录为**461、840、923、1195、1355、1495**。其中461、1195、1355、1495为竖向ditto；**840、923是真实多行正文输入，Paddle没有返回其中可读的文字**。
- 840包含Israel条目的三行；923包含Orlando R、Ralph C、Rebecca三行。这两个crop的共享分割先有问题，但Paddle的空输出仍是真实的信息丢失，不能说它的6个空值全部无关紧要。
- mOCR的7个空值中，至少167页记录1467是清楚的非空续行漏识别；其他若干来自符号/极小框。不能将空值数量直接等同漏居民数量。

### 同一文字落入多框，生成式模型容易重复输出

- 161页记录15：Aaron Abraham框中同时包含上一行Aalto J；mOCR/Qwen均带入Aalto，和上一记录重复。
- 163页记录365、411、424等：框覆盖上下两行，造成合并输出或交错乱码。Paddle在365也缺字，并非消除了这种影响。
- 165页记录838–841：Israel条目的三行多次落入不同框。mOCR/Qwen输出较完整，却把相同正文重复放入多个CSV单元格。
- 166页记录1255–1256：mOCR/Qwen在1255读出正文与`av h do`，1256又输出一次续行。

上述额外文字确实在输入图内，应称为共享框与逐行输出边界问题，区别于第4节中无图像依据的新内容。

### ditto符号被当成独立文字行

- 161页记录89、163页461、166页1195、167页1355等为竖向ditto条。Tesseract会生成字母乱码；Easy/Paddle可能为空、数字或标点；mOCR/Qwen可能进入引号循环。
- 165页记录944和945的两个框甚至落在同一个ditto上，造成重复符号记录。
- 164页记录594等有些姓名左侧ditto完全在crop之外，模型不能从缺符号的图片中恢复它。

因此，1,573条检测行不是1,573条正确物理行或1,573名居民。所有模型共用的几何信息也不是gold。

## 6. 可以用于团队沟通的最终结论

1. **多模型OCR产出阶段已覆盖五个模型**，所有输入均有运行记录，结果可逐行回到同一原扫描图；没有发现导出错位。
2. **不同模型的优势确实不同**：Paddle修复部分常规单行姓名/首字母；mOCR/Qwen恢复部分难词、分数门牌和续行；EasyOCR也能修复部分Tesseract人名错误。无法用少数例子宣布一个全面赢家。
3. **当前最应突出的是忠实性与结构问题**：Qwen有明确、不可由crop解释的编造，当前整列不能直接当忠实转录；mOCR有生成循环、跨行/重复及少数非空续行漏识别；传统模型同样有错字、丢字及伪行乱码。
4. 本轮看图中，Paddle是常规单行的有价值候选对照，mOCR对困难文字有补充价值；这不是正式模型排名，更不意味着可自动用某个模型覆盖全部其他结果。
5. 本报告不生成融合“正确答案”，不纠正主CSV，也不计算CER/WER或字段准确率；这些需要组员的独立人工参考。这里交付的是五模型最终输出的具体错误分析。

## 7. 方法和配置边界

本次做了全量文件/索引/raw一致性检查、覆盖七页的定向图像抽查，以及Paddle全部6个空输出的逐个看图核对；不是1,573条的完整人工转录。保留原结果，未修改pipeline、扫描图或CSV。

Tesseract是历史整页PSM3结果，mOCR/Easy/Paddle/Qwen使用共享行裁图，输入上下文不同；不能将整页与裁图差异都解释成模型能力差异。

当前模型为Tesseract5.3.4+tessdata_best、dots-studio/dots.mocr、EasyOCR1.7.2/english_g2、PaddleOCR3.7.0/en_PP-OCRv5_mobile_rec（CPU）、Qwen/Qwen3-VL-2B-Instruct（T4、FP16、SDPA）。各自配置/版本在`results/models.json`。没有可比的五模型计时序列，因此本报告不做速度排名。


## 8. 效率与计算资源汇总

客户关于更大规模compute resource的问题，至少涉及处理速度、设备种类、内存/显存以及首次加载成本。**目前只有Tesseract与mOCR保存了可计算的实际处理时间；其余三个模型的耗时未记录，不能由输出结果反推。**

### 五模型现有证据

| 模型 | 实际记录的设备/配置 | 已记录处理耗时 | 按原始七页计算的平均 | RAM/VRAM峰值 |
|---|---|---|---|---|
| Tesseract | CPU；历史整页PSM3；CPU型号/线程未完整记录 | **130.287秒（2.17分钟）**，七次整页运行 | **18.612秒/页** | 未测量 |
| mOCR | Tesla T4，bf16/SDPA；逐行 | **1,181.701秒（19.70分钟）**，原始1,737次请求 | **168.814秒/页**；**0.680秒/请求** | 未测量 |
| EasyOCR | Tesla T4，FP32；逐行 | **未记录** | 无法计算 | 未测量 |
| PaddleOCR | CPU，FP32；配置2个CPU线程；逐行 | **未记录** | 无法计算 | 未测量 |
| Qwen3-VL-2B | Tesla T4，FP16/SDPA；逐行 | **未记录** | 无法计算 | 未测量 |

“配置2线程”不是已测CPU利用率；T4是设备型号，不是实际显存占用量。FP32/FP16/bf16为精度设置，也不能代替内存测量。统一pipeline没有给后三个模型写入duration/seconds字段，因此这是本轮日志的真实缺口，不是模型尚未运行。

### 原七页与当前CSV范围必须区分

表中mOCR采用原始七页的全部1,737次请求，与Tesseract七次整页历史运行对应。当前CSV仅保留1,573行，排除了第161页顶部缩写表和页脚。

筛选当前1,573行所对应的既有mOCR请求日志，可得到：

- 合计 **1,123.987秒，18.733分钟**；平均 **0.714550秒/行**。
- 除以七个页面范围为 **160.570秒/页范围**；第161页仅正文，这不是一般完整页面的新实测。
- 这是对旧日志的过滤加总，没有重新运行OCR。
- 所有completed、empty、truncated请求都计入耗时，不能只统计成功输出而忽略失败成本。
- 其中11条truncated请求消耗 **104.191秒**，占当前范围日志时间约 **9.27%**。本批引号/Dor重复生成不仅影响文字质量，也消耗处理时间；这个比例不是准确率。

Tesseract没有实测单行延迟，不能把整页时间除行数冒充逐行OCR latency。

### 计时实际包含什么

已从原实现核对计时位置：

- **Tesseract**：图像预处理之后开始，包含引擎进程启动、OCR子进程和临时图删除；不含源图下载、图像预处理、TSV解析及导出。
- **mOCR**：行裁图和PNG/base64准备之后开始，包含输入处理、生成、解码及少量Python操作；不含模型下载/初次加载、取图编码和导出。旧实现未显式CUDA synchronize，应称为日志记录的请求处理耗时，而不是隔离GPU kernel时间。
- 两者均不是整个notebook端到端wall-clock，也不是CPU/GPU实际活跃计算秒数或利用率。
- 从新扫描图开始，mOCR等逐行识别还需要上游行坐标准备。历史Tesseract与mOCR两阶段记录加总 **1,311.988秒（21.87分钟）**，仍未覆盖所有下载/预处理/加载/导出开销。已有共用行坐标可复用，不能把复用当作重新检测的速度。

### 能否用于更大volume的估计

按既有计时范围折算，Tesseract约 **193.42页/处理小时**，mOCR原七页约 **21.33页/请求处理小时**。这两个数反映当前实现、设备和输入粒度，不能作同条件的模型速度排行榜，也不是实际生产端到端吞吐保证。

七页样本不足以给整册确定工时。页面分辨率、每页行数、符号伪行、生成循环、批量大小、硬件、首次加载与重试都会影响结果。扩量的合适表述是“在本次配置下已观察到的处理时间”，而不是普遍模型性能结论。

完整五模型资源比较仍需补测：统一页面/行范围，分别记录模型加载、新请求处理、导出和总wall-clock；区分缓存复用；记录硬件、CPU线程及峰值RAM/VRAM。无需重新做准确率评估，但现有日志无法事后还原后三个模型的平均时间。

### 可直接用于client沟通的英文表述

> We currently have partial runtime evidence rather than a complete five-model compute benchmark. In the original seven-page run, Tesseract recorded 130.3 seconds of full-page engine processing on CPU, or 18.6 seconds per page. mOCR recorded 1,181.7 seconds across 1,737 line requests on a Tesla T4, or 168.8 seconds per page. These measurements exclude several setup and export stages and use different input granularities. EasyOCR, PaddleOCR and Qwen have recorded hardware configurations but no saved timing or peak-memory measurements. A consistent runtime and memory measurement is still needed before estimating full-volume requirements across all five models.

证据文件：`fa26/bpl_ocrs/results/raw/tesseract_pages/runtime.json`、`raw/dots_mocr.jsonl`、`raw/dots_mocr_runtime.json`及`results/models.json`。后三个模型raw文件及当前共享Python源码已核对，未找到计时或内存telemetry。未重跑模型，未修改原始结果。
