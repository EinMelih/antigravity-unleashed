import math
import re
from collections import Counter

def tokenize(text):
    """Split text into lowercase alphanumeric words."""
    return re.findall(r'\w+', text.lower())

class LightweightSemanticSearch:
    def __init__(self, documents):
        self.documents = documents
        self.tokenized_docs = [tokenize(doc) for doc in documents]
        self.num_docs = len(documents)
        self.idf = self._compute_idf()
        self.doc_vectors = [self._vectorize(doc) for doc in self.tokenized_docs]

    def _compute_idf(self):
        """Compute Inverse Document Frequency for all terms in the corpus."""
        doc_frequencies = Counter()
        for doc in self.tokenized_docs:
            unique_words = set(doc)
            for word in unique_words:
                doc_frequencies[word] += 1
        
        idf = {}
        for word, count in doc_frequencies.items():
            # Additive smoothing to prevent division by zero
            idf[word] = math.log(1 + (self.num_docs / count))
        return idf

    def _vectorize(self, tokenized_text):
        """Convert tokenized text into a sparse TF-IDF vector dict."""
        tf = Counter(tokenized_text)
        vector = {}
        for word, count in tf.items():
            if word in self.idf:
                vector[word] = count * self.idf[word]
        return vector

    def search(self, query, top_k=3):
        """Search the document index using sparse cosine similarity."""
        query_tokens = tokenize(query)
        query_vector = {}
        query_tf = Counter(query_tokens)
        for word, count in query_tf.items():
            if word in self.idf:
                query_vector[word] = count * self.idf[word]

        results = []
        for idx, doc_vector in enumerate(self.doc_vectors):
            similarity = self._sparse_cosine_similarity(query_vector, doc_vector)
            results.append((similarity, self.documents[idx]))
        
        # Sort by similarity score descending
        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_k]

    def _sparse_cosine_similarity(self, vec_a, vec_b):
        """Compute cosine similarity between two sparse dict vectors."""
        intersection = set(vec_a.keys()) & set(vec_b.keys())
        if not intersection:
            return 0.0
        
        dot_product = sum(vec_a[x] * vec_b[x] for x in intersection)
        mag_a = math.sqrt(sum(val * val for val in vec_a.values()))
        mag_b = math.sqrt(sum(val * val for val in vec_b.values()))
        
        if mag_a == 0.0 or mag_b == 0.0:
            return 0.0
        return dot_product / (mag_a * mag_b)
