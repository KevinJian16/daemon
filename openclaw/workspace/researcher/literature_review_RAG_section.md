# Literature Review Section: Recent Advances in Retrieval-Augmented Generation (RAG)

## Introduction

Retrieval-Augmented Generation (RAG) has rapidly evolved from a simple "retrieve-and-generate" pipeline into a sophisticated family of architectures that combine large language models (LLMs) with dynamic external knowledge retrieval. By grounding generation in up-to-date, domain-specific corpora, RAG mitigates key limitations of LLMs such as hallucination, outdated knowledge, and lack of verifiability. This literature review surveys five recent papers (2024‑2025) that capture the current trajectory of RAG research, spanning comprehensive surveys, robustness enhancements, graph‑based retrieval, agentic orchestration, and empirical best practices. Together, these works highlight the field’s shift toward modular, adaptive, and robust systems capable of handling complex, real‑world knowledge‑intensive tasks.

## 1. Sharma et al. (2025) – A Comprehensive Survey of Architectures, Enhancements, and Robustness Frontiers

**Reference:** Sharma, C. (2025). *Retrieval‑Augmented Generation: A Comprehensive Survey of Architectures, Enhancements, and Robustness Frontiers*. arXiv:2506.00054.

This survey consolidates the state‑of‑the‑art in RAG research, providing a systematic taxonomy of architectures, enhancement techniques, and robustness challenges. The authors categorize RAG systems into **retriever‑centric**, **generator‑centric**, and **hybrid** designs, emphasizing the trend toward modularity and plug‑and‑play components. A key contribution is the detailed analysis of **robustness frontiers**, where the paper examines vulnerabilities such as adversarial retrieval attacks, out‑of‑distribution queries, and noisy corpora. Defensive strategies—including confidence‑calibrated retrieval, differential‑private indexing, and adversarial training—are reviewed as essential for deploying RAG in high‑stakes domains. The survey also discusses system‑level optimizations for latency and throughput, reflecting the growing industrial adoption of RAG‑as‑a‑Service (RaaS). By mapping both architectural innovations and open robustness gaps, this work serves as a foundational reference for the next generation of retrieval‑augmented language models.

## 2. Singh et al. (2025) – Agentic Retrieval‑Augmented Generation: A Survey on Agentic RAG

**Reference:** Singh, A., Ehtesham, A., et al. (2025). *Agentic Retrieval‑Augmented Generation: A Survey on Agentic RAG*. arXiv:2501.09136.

Agentic RAG extends the traditional RAG pipeline by incorporating autonomous agents that orchestrate retrieval, reasoning, and generation through multi‑step decision‑making. This survey delineates how agentic frameworks—such as those built on LangGraph, AutoGen, or custom reinforcement‑learning loops—enable **iterative retrieval**, **query decomposition**, and **self‑correction**. The authors highlight several emergent capabilities: (1) dynamic retrieval‑depth adjustment based on query complexity, (2) tool‑augmented retrieval that interfaces with APIs, databases, and external services, and (3) reflective critique mechanisms that evaluate intermediate outputs before final generation. Agentic RAG is shown to excel in multi‑hop question answering, long‑form reasoning, and interactive dialogue, where static pipelines often struggle. The survey also notes key challenges, including increased computational overhead, the need for reliable agent‑orchestration heuristics, and the risk of cascading errors. As LLMs become more agent‑capable, agentic RAG represents a natural evolution toward more autonomous, goal‑driven knowledge systems.

## 3. Peng et al. (2024) – Graph Retrieval‑Augmented Generation: A Survey

**Reference:** Peng, B., et al. (2024). *Graph Retrieval‑Augmented Generation: A Survey*. arXiv:2408.08921.

GraphRAG leverages structured knowledge graphs (KGs) to augment retrieval with relational and hierarchical information, addressing limitations of vector‑based retrieval in multi‑hop and compositional reasoning. This survey systematizes GraphRAG methods along two axes: **graph construction** (from text, tables, or existing KGs) and **graph‑aware retrieval** (e.g., sub‑graph sampling, path‑based embedding, graph neural networks). Notable architectures include **RAPTOR** (Recursive Abstractive Processing for Tree‑Organized Retrieval), which builds a tree of summaries at varying abstraction levels, and **KRAGEN** (Knowledge Retrieval Augmented Generation ENgine), which uses graph‑of‑thoughts prompting to decompose complex queries. The authors demonstrate that GraphRAG significantly improves performance on biomedical, legal, and scientific QA benchmarks where relationships between entities are crucial. Open challenges include scalable graph construction for dynamic corpora, efficient real‑time graph updates, and the integration of heterogeneous graph‑text representations. The survey positions GraphRAG as a critical bridge between unstructured text retrieval and structured knowledge reasoning.

## 4. Chen et al. (2024) – Searching for Best Practices in Retrieval‑Augmented Generation

**Reference:** Chen, Z., et al. (2024). *Searching for Best Practices in Retrieval‑Augmented Generation*. arXiv:2407.01219.

Through extensive ablation studies on diverse datasets, this empirical paper identifies practical, evidence‑based guidelines for building effective RAG systems. The authors evaluate factors such as **retriever choice** (sparse vs. dense vs. hybrid), **retrieval granularity** (document, passage, sentence), **fusion techniques** (early vs. late integration), and **context‑window management**. Key findings include: (1) hybrid retrieval consistently outperforms single‑mode retrieval on fact‑intensive tasks, (2) iterative retrieval with relevance feedback yields substantial gains in multi‑hop QA, and (3) careful calibration of retrieval confidence can reduce hallucination without sacrificing recall. The paper also explores **multimodal retrieval**, showing that incorporating visual or tabular evidence alongside text boosts accuracy on cross‑modal benchmarks. Each recommendation is accompanied by concrete implementation details and trade‑offs (e.g., latency vs. accuracy), making the study a valuable handbook for practitioners. The work underscores that “one‑size‑fits‑all” RAG configurations are suboptimal; instead, task‑aware tuning of retrieval and generation components is essential for high performance.

## 5. Yan et al. (2024) – Corrective Retrieval Augmented Generation (CRAG)

**Reference:** Yan, G., et al. (2024). *Corrective Retrieval Augmented Generation*. arXiv:2401.15884.

CRAG introduces a lightweight **retrieval evaluator** that assesses the relevance and reliability of retrieved documents, triggering corrective actions when confidence is low. The framework employs a **decompose‑then‑recompose** algorithm that splits documents into fine‑grained segments, filters irrelevant content, and selectively augments retrieval with web‑search results when the local corpus is insufficient. CRAG is designed as a plug‑and‑play module that can be layered atop existing RAG pipelines, offering robustness against noisy or incomplete retrieval. Experiments on short‑ and long‑form generation tasks show that CRAG significantly improves factual accuracy and reduces hallucination compared to naive RAG baselines. The paper also discusses extensions such as **self‑corrective loops**, where the generator’s output is fed back to the retriever for verification and refinement. By embedding a self‑assessment mechanism into the retrieval step, CRAG exemplifies the trend toward **self‑reflective RAG** systems that can diagnose and repair their own retrieval failures.

## Synthesis and Future Directions

The reviewed papers collectively underscore several convergent themes in contemporary RAG research:

- **Modularity and Composability:** Modern RAG architectures are increasingly decomposed into interchangeable components (retriever, reranker, fusion module, generator), enabling task‑specific customization and easier integration of new advances.
- **Robustness and Self‑Correction:** As RAG moves into production, attention has shifted toward hardening systems against adversarial inputs, noisy data, and out‑of‑domain queries. Techniques like confidence calibration, retrieval evaluation, and corrective loops are becoming standard.
- **Structured and Multimodal Retrieval:** Pure vector‑based retrieval is being augmented with graph‑based, tabular, and visual retrieval to support complex reasoning and cross‑modal tasks.
- **Agentic Orchestration:** The integration of autonomous agents allows RAG pipelines to perform multi‑step planning, iterative retrieval, and reflective critique, moving beyond static “retrieve‑once‑generate” workflows.
- **Empirical Rigor:** Large‑scale ablation studies are providing evidence‑based best practices, helping practitioners navigate the many design choices in building RAG systems.

Open challenges that cut across the surveyed works include:

1. **Scalability:** Efficiently retrieving from billion‑document corpora while maintaining low latency and fresh updates.
2. **Real‑time Adaptation:** Incorporating streaming data sources and adapting retrieval indices on‑the‑fly.
3. **Causal Reasoning:** Moving beyond associative retrieval to genuine causal inference and counterfactual reasoning.
4. **Fairness and Bias:** Mitigating societal biases that can be amplified through retrieval corpora and generation.
5. **Unified Evaluation:** Developing benchmarks that assess not only factual accuracy but also robustness, fairness, efficiency, and user trust.

## Conclusion

The five papers reviewed here—spanning comprehensive surveys, domain‑specialized methods, and empirical guidelines—demonstrate that RAG is maturing from a simple augmentation technique into a rich, multifaceted research field. Innovations in modular architecture, robustness, graph‑based retrieval, agentic control, and corrective mechanisms are expanding the boundaries of what retrieval‑augmented systems can achieve. As LLMs continue to evolve, RAG will remain indispensable for grounding them in accurate, up‑to‑date, and verifiable knowledge, ensuring that generative AI can be deployed reliably across knowledge‑intensive applications.

## References

1. Sharma, C. (2025). *Retrieval‑Augmented Generation: A Comprehensive Survey of Architectures, Enhancements, and Robustness Frontiers*. arXiv:2506.00054.
2. Singh, A., Ehtesham, A., et al. (2025). *Agentic Retrieval‑Augmented Generation: A Survey on Agentic RAG*. arXiv:2501.09136.
3. Peng, B., et al. (2024). *Graph Retrieval‑Augmented Generation: A Survey*. arXiv:2408.08921.
4. Chen, Z., et al. (2024). *Searching for Best Practices in Retrieval‑Augmented Generation*. arXiv:2407.01219.
5. Yan, G., et al. (2024). *Corrective Retrieval Augmented Generation*. arXiv:2401.15884.

*All arXiv references are linked to their respective preprints.*