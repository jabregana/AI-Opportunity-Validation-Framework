"""Neural embedder adapter using model2vec (distilled static embeddings).

model2vec distills a real sentence transformer into a static lookup
table. Inference is token lookup + averaging, with no PyTorch at
runtime. Order-of-microseconds per embedding on CPU.

Default model: minishlab/potion-base-32M (~130MB on disk). The smaller
potion-base-8M is also tested but its paraphrase signal is too weak
on short relation names (cosine 0.13 on IsA<->INSTANCE_OF).

Sentence template: bare short tokens like "IsA" produce weak signal
even on the 32M model because the underlying encoder was trained on
sentences, not tokens. Wrapping the input in a fixed template
("the relation type called X") substantially raises paraphrase
similarity (IsA<->INSTANCE_OF: 0.13 -> 0.71 raw to template).

Known limitation: the template also raises false-positive similarity
on antonyms and siblings (Synonym<->Antonym: 0.65; LOCATED_IN<->
LOCATED_NEAR: 0.93). This is the classic distributional-semantics
antonym problem. UC-4.4 Tier B is the explicit gate for catching these
false positives.

This module is imported lazily by NeuralEmbeddingSchemaProxy so the
rest of the harness does not pay the model2vec import cost.
"""
from __future__ import annotations


class Model2VecEmbedder:
    """Embedder adapter wrapping model2vec.StaticModel.

    Vectors are L2-normalized on output. Optional sentence template
    wraps inputs before encoding to raise paraphrase signal on short
    tokens.
    """

    def __init__(
        self,
        model_name: str = "minishlab/potion-base-32M",
        template: str | None = "the relation type called {}",
    ):
        from model2vec import StaticModel

        self._model = StaticModel.from_pretrained(model_name)
        self.model_name = model_name
        self.template = template
        sample = self._model.encode(self._render("probe")).tolist()
        self._dim = len(sample)

    def _render(self, text: str) -> str:
        return self.template.format(text) if self.template else text

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        v = self._model.encode(self._render(text)).tolist()
        norm_sq = sum(x * x for x in v)
        if norm_sq <= 0:
            return v
        inv = 1.0 / (norm_sq**0.5)
        return [x * inv for x in v]
