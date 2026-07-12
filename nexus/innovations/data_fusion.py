import logging
from typing import Dict, List, Optional, Any, Tuple, Set
from rapidfuzz import fuzz

logger = logging.getLogger("nexus.innovations.data_fusion")


class DataFusionEngine:
    """
    DataFusionEngine merges and resolves data records scraped from multiple domains.
    It performs entity resolution using exact identifiers (e.g., SKU, EAN) and fuzzy string similarity,
    groups them into entity clusters, and fuses each cluster into a single consolidated record
    with calculated field-level confidence scores.
    """

    def __init__(self, domain_weights: Optional[Dict[str, float]] = None, resolution_threshold: float = 0.8) -> None:
        self.domain_weights = domain_weights or {}
        self.resolution_threshold = resolution_threshold

    def get_domain_weight(self, domain: str) -> float:
        """Returns the reliability weight of a domain (defaults to 0.5 if unregistered)."""
        return self.domain_weights.get(domain, 0.5)

    def calculate_similarity(self, r1: Dict[str, Any], r2: Dict[str, Any]) -> float:
        """
        Calculates a similarity score [0.0 - 1.0] between two records based on
        exact match of strong identifiers (SKU, EAN) or fuzzy string matching on text fields (title/name).
        """
        # 1. Hard identifiers: SKU or EAN/UPC exact matches take precedence
        for id_field in ['sku', 'ean', 'upc', 'model_number']:
            v1 = r1.get(id_field)
            v2 = r2.get(id_field)
            if v1 is not None and v2 is not None:
                val1 = str(v1).strip().lower()
                val2 = str(v2).strip().lower()
                if val1 and val2 and val1 != 'none' and val2 != 'none':
                    if val1 == val2:
                        return 1.0
                    else:
                        return 0.0

        # 2. Fuzzy text matching on title or name
        t1 = str(r1.get('title', r1.get('name', ''))).strip()
        t2 = str(r2.get('title', r2.get('name', ''))).strip()
        
        if not t1 or not t2:
            return 0.0

        # Use rapidfuzz token_sort_ratio and token_set_ratio for robust string comparison
        text_similarity = max(fuzz.token_sort_ratio(t1, t2), fuzz.token_set_ratio(t1, t2)) / 100.0

        # Optional secondary field: brand check
        brand1 = r1.get('brand')
        brand2 = r2.get('brand')
        if brand1 and brand2:
            b1 = str(brand1).strip().lower()
            b2 = str(brand2).strip().lower()
            if b1 and b2 and b1 != 'none' and b2 != 'none':
                if b1 != b2 and fuzz.ratio(b1, b2) < 80:
                    # Different brands -> reduce similarity score significantly
                    text_similarity *= 0.3

        return text_similarity

    def cluster_records(self, records: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """
        Groups similar records into clusters using single-linkage clustering.
        Each cluster represents a unique entity.
        """
        if not records:
            return []

        clusters: List[List[Dict[str, Any]]] = []
        for r in records:
            assigned = False
            for cluster in clusters:
                # Compare record against elements in the cluster
                # We check if there's any record in the cluster with similarity >= threshold
                if any(self.calculate_similarity(r, cr) >= self.resolution_threshold for cr in cluster):
                    cluster.append(r)
                    assigned = True
                    break
            if not assigned:
                clusters.append([r])

        logger.info(f"Grouped {len(records)} raw records into {len(clusters)} distinct entity clusters.")
        return clusters

    def _fuse_string_field(self, values_with_weights: List[Tuple[str, float]]) -> Tuple[str, float]:
        """
        Fuses string values by finding the consensus, preferring the longest/most descriptive string
        among agreeing values, and calculates its confidence.
        """
        if not values_with_weights:
            return "", 0.0

        # Find best value based on weighted agreement
        # To handle minor differences, we cluster strings using fuzzy matching
        string_clusters: List[List[Tuple[str, float]]] = []
        for val, weight in values_with_weights:
            added = False
            for s_cluster in string_clusters:
                # Compare with first item in cluster
                if fuzz.token_set_ratio(val, s_cluster[0][0]) >= 85:
                    s_cluster.append((val, weight))
                    added = True
                    break
            if not added:
                string_clusters.append([(val, weight)])

        # Select cluster with highest total weight
        best_cluster = max(string_clusters, key=lambda c: sum(item[1] for item in c))
        
        # Choose the representative value from the best cluster (highest weight, with length as tie-breaker)
        best_val = max(best_cluster, key=lambda item: (item[1], len(item[0])))[0]

        # Calculate confidence
        total_cluster_weight = sum(item[1] for item in best_cluster)
        total_all_weight = sum(w for _, w in values_with_weights)
        agreement_ratio = len(best_cluster) / len(values_with_weights)
        
        # Confidence formula: combines agreement ratio and the relative weight of the agreeing cluster
        weight_ratio = total_cluster_weight / total_all_weight if total_all_weight > 0 else 0.0
        confidence = (agreement_ratio * 0.5) + (weight_ratio * 0.5)

        return best_val, min(confidence, 1.0)

    def _fuse_numeric_field(self, values_with_weights: List[Tuple[float, float]]) -> Tuple[float, float]:
        """
        Fuses numeric values (like prices) by finding values within a 5% difference margin,
        aggregating them by average, and calculates confidence.
        If there is an exact consensus (multiple sources reporting the exact same number),
        that exact value is preferred.
        """
        if not values_with_weights:
            return 0.0, 0.0

        # Check for exact consensus
        exact_counts = {}
        exact_weights = {}
        for val, weight in values_with_weights:
            exact_counts[val] = exact_counts.get(val, 0) + 1
            exact_weights[val] = exact_weights.get(val, 0.0) + weight

        # If we have an exact consensus (more than 1 source has the exact same value)
        # choose the exact value with the highest total weight
        consensus_vals = [val for val, count in exact_counts.items() if count > 1]
        if consensus_vals:
            best_consensus_val = max(consensus_vals, key=lambda v: exact_weights[v])
            agreement_ratio = exact_counts[best_consensus_val] / len(values_with_weights)
            total_all_weight = sum(w for _, w in values_with_weights)
            weight_ratio = exact_weights[best_consensus_val] / total_all_weight if total_all_weight > 0 else 0.0
            confidence = (agreement_ratio * 0.4) + (weight_ratio * 0.6)
            return round(best_consensus_val, 2), min(confidence, 1.0)

        # Cluster numeric values that are close to each other (within 5% range)
        num_clusters: List[List[Tuple[float, float]]] = []
        for val, weight in values_with_weights:
            added = False
            for n_cluster in num_clusters:
                # Compare with average of cluster
                avg_cluster_val = sum(item[0] for item in n_cluster) / len(n_cluster)
                if abs(val - avg_cluster_val) / max(avg_cluster_val, 1e-5) <= 0.05:
                    n_cluster.append((val, weight))
                    added = True
                    break
            if not added:
                num_clusters.append([(val, weight)])

        # Select cluster with highest total weight
        best_cluster = max(num_clusters, key=lambda c: sum(item[1] for item in c))
        
        # Represent value as the weighted average of the best cluster
        best_val = sum(v * w for v, w in best_cluster) / sum(w for _, w in best_cluster)

        # Confidence calculation
        agreement_ratio = len(best_cluster) / len(values_with_weights)
        total_cluster_weight = sum(item[1] for item in best_cluster)
        total_all_weight = sum(w for _, w in values_with_weights)
        weight_ratio = total_cluster_weight / total_all_weight if total_all_weight > 0 else 0.0

        confidence = (agreement_ratio * 0.4) + (weight_ratio * 0.6)
        return round(best_val, 2), min(confidence, 1.0)

    def fuse_cluster(self, cluster: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Fuses a list of similar records (representing the same entity) into a single unified record.
        Maintains field-level confidence scores.
        """
        if not cluster:
            return {}

        fused_record: Dict[str, Any] = {}
        confidence_scores: Dict[str, float] = {}
        sources: List[str] = []

        # Gather metadata
        for r in cluster:
            domain = r.get('domain', 'unknown')
            sources.append(domain)

        fused_record['sources'] = list(set(sources))

        # Collect all fields across all records in the cluster
        all_fields: Set[str] = set()
        for r in cluster:
            all_fields.update(r.keys())

        # Discard system/metadata fields from dynamic consolidation
        all_fields.difference_update({'domain', 'sources', '_confidence'})

        # Fuse each field
        for field in all_fields:
            # Extract non-null values with their domain weight
            field_data: List[Tuple[Any, float]] = []
            for r in cluster:
                val = r.get(field)
                if val is not None and str(val).strip() != '':
                    domain_weight = self.get_domain_weight(r.get('domain', 'unknown'))
                    field_data.append((val, domain_weight))

            if not field_data:
                fused_record[field] = None
                confidence_scores[field] = 0.0
                continue

            # Check data type of the field to use the proper fusion algorithm
            sample_val = field_data[0][0]

            if isinstance(sample_val, (int, float)) and field in ['price', 'old_price', 'rating', 'stock']:
                # Cast all values to float for safety
                numeric_data = [(float(v), w) for v, w in field_data]
                best_val, conf = self._fuse_numeric_field(numeric_data)
                fused_record[field] = best_val
                confidence_scores[field] = conf
            elif isinstance(sample_val, dict):
                # For dictionaries (like attributes), we recursively merge keys
                fused_dict = {}
                dict_confidences = {}
                sub_keys = set()
                for d, _ in field_data:
                    sub_keys.update(d.keys())

                for sk in sub_keys:
                    sk_data = []
                    for d, w in field_data:
                        sv = d.get(sk)
                        if sv is not None and str(sv).strip() != '':
                            sk_data.append((sv, w))
                    
                    if not sk_data:
                        continue

                    # Fuse subkey as a string
                    str_sk_data = [(str(v), w) for v, w in sk_data]
                    best_sk_val, sk_conf = self._fuse_string_field(str_sk_data)
                    fused_dict[sk] = best_sk_val
                    dict_confidences[sk] = sk_conf

                fused_record[field] = fused_dict
                confidence_scores[field] = sum(dict_confidences.values()) / len(dict_confidences) if dict_confidences else 1.0
            else:
                # String / Categorical field fusion
                str_data = [(str(v), w) for v, w in field_data]
                best_val, conf = self._fuse_string_field(str_data)
                # Recover type if possible (e.g. bool)
                if str(best_val).lower() == 'true':
                    fused_record[field] = True
                elif str(best_val).lower() == 'false':
                    fused_record[field] = False
                else:
                    fused_record[field] = best_val
                confidence_scores[field] = conf

        # Add confidence scores metadata
        fused_record['_confidence'] = confidence_scores
        # Overall entity confidence is the average confidence of its core fields (title, price)
        core_confs = [confidence_scores.get(f, 0.0) for f in ['title', 'price'] if f in confidence_scores]
        fused_record['confidence_score'] = sum(core_confs) / len(core_confs) if core_confs else sum(confidence_scores.values()) / len(confidence_scores)

        return fused_record

    def fuse_all(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Performs end-to-end entity resolution and data fusion.
        Takes raw list of records from multiple domains and returns fused consolidated records.
        """
        clusters = self.cluster_records(records)
        fused_records = []
        for cluster in clusters:
            fused_records.append(self.fuse_cluster(cluster))
        return fused_records
