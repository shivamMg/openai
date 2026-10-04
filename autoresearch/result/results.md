# Autoresearch results

![ROUGE-L results](results.png)

| run_id | model_id | kind | epochs | lrm | batch size | rouge_l | delta_vs_base | eval_count | description |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base-20261003T055813854041Z-f20494 | gpt-4.1-nano | base | — | — | — | 0.1354 | 0.0000 | 100/100 | Base GPT-4.1-nano |
| sft-20261003T062945390909Z-503fc5 | gpt-4.1-nano-2025-04-14.ft-6dae574b63474a92851f39ca51f0638a-auto-c135ebb7 | sft | 1 | 0.1000 | auto | 0.2065 | 0.0711 | 93/100 | Baseline SFT improved mean ROUGE-L by 0.0711 versus base; 93 scored and 7 content-filtered rows |
| sft-20261003T092447033004Z-282779 | gpt-4.1-nano-2025-04-14.ft-4cd6ff3d7d364efe87a7b61e841c166c-auto-e7728b22 | sft | 2 | 0.1000 | auto | 0.2237 | 0.0884 | 94/100 | Two epochs improved mean ROUGE-L by 0.0172 versus the one-epoch SFT; 94 scored and 6 content-filtered rows |
| sft-20261003T112326756160Z-8929f0 | gpt-4.1-nano-2025-04-14.ft-444ca08ff141449fbbc8671ecc14ca0b-auto-c11e695e | sft | 3 | 0.1000 | auto | 0.2216 | 0.0862 | 97/100 | Three epochs scored 0.0022 below the retained two-epoch SFT; 97 scored and 3 content-filtered rows |
| sft-20261004T032116487071Z-0a218b | gpt-4.1-nano-2025-04-14.ft-a92cf006bbdf46d89da010de04a8f610-auto-e47c6763 | sft | 2 | 0.5000 | 1 | 0.2140 | 0.0784 | 97/100 | LRM 0.5000 scored 0.0097 below the retained two-epoch SFT; 97 scored and 3 content-filtered rows |
| sft-20261004T051614007367Z-c35a42 | gpt-4.1-nano-2025-04-14.ft-35509e240d434f7daebcd1e218e3f9df-auto-e08da53a | sft | 2 | 1.0000 | 1 | 0.2141 | 0.0785 | 93/100 | LRM 1.0000 scored 0.0097 below the retained two-epoch SFT (different evaluation protocols); 93 scored and 7 content-filtered rows; baseline base-20261002T155033700805Z-a3d40d |
| **sft-20261004T081018977000Z-6b1252** | **gpt-4.1-nano-2025-04-14.ft-c507565f095a4fcbbe45be3975940de0-auto-7305d66f** | **sft** | **2** | **0.1000** | **2** | **0.2270** | **0.0914** | **94/100** | **Batch size 2 improved mean ROUGE-L by 0.0033 versus the retained two-epoch SFT; 94 scored and 6 content-filtered rows** |
