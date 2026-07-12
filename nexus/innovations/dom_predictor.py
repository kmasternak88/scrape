import logging
import numpy as np
from bs4 import BeautifulSoup, Tag
from rapidfuzz import fuzz
from sklearn.ensemble import RandomForestClassifier
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("nexus.innovations.dom_predictor")


def get_sibling_index(element: Tag) -> int:
    """Gets the 0-based index of the element among its sibling tags."""
    parent = element.parent
    if not parent:
        return 0
    siblings = [c for c in parent.contents if isinstance(c, Tag)]
    try:
        return siblings.index(element)
    except ValueError:
        return 0


def get_depth(element: Tag) -> int:
    """Calculates the depth of the element in the DOM tree."""
    depth = 0
    current = element
    while current.parent:
        depth += 1
        current = current.parent
    return depth


def generate_selector(element: Tag) -> str:
    """Generates a highly specific and unique CSS selector for the given element."""
    if element.get('id'):
        element_id = element.get('id')
        if isinstance(element_id, list):
            element_id = " ".join(element_id)
        if not any(c.isdigit() for c in element_id) or len(element_id) < 15:
            return f"{element.name}#{element_id}"

    parts = []
    current = element
    while current and current.name != '[document]':
        tag_name = current.name
        classes = current.get('class')
        if classes:
            if isinstance(classes, list):
                class_str = ".".join([c for c in classes if c])
            else:
                class_str = str(classes).replace(" ", ".")
            if class_str:
                tag_name = f"{tag_name}.{class_str}"

        parent = current.parent
        if parent:
            siblings = parent.find_all(current.name, recursive=False)
            if len(siblings) > 1:
                index = siblings.index(current) + 1
                tag_name = f"{tag_name}:nth-of-type({index})"

        parts.insert(0, tag_name)
        current = current.parent

    return " > ".join(parts)


class DOMPredictor:
    """
    DOMPredictor uses machine learning (RandomForestClassifier) and fuzzy matching
    to predict and heal broken CSS selectors when web pages change.
    """

    def __init__(self) -> None:
        self.models: Dict[str, RandomForestClassifier] = {}
        self.targets: Dict[str, Dict[str, Any]] = {}

    def extract_relative_features(self, element: Tag, target: Dict[str, Any]) -> List[float]:
        """Extracts numerical features of an element relative to the target element's properties."""
        # 1. Tag name similarity
        is_same_tag = 1.0 if element.name == target['tag'] else 0.0

        # 2. Parent tag similarity
        parent_name = element.parent.name if element.parent else ""
        is_same_parent = 1.0 if parent_name == target['parent_tag'] else 0.0

        # 3. Child count diff
        child_count = len(element.find_all(recursive=False))
        child_count_diff = float(abs(child_count - target['child_count']))

        # 4. Depth diff
        depth = get_depth(element)
        depth_diff = float(abs(depth - target['depth']))

        # 5. Text length diff
        text = element.get_text().strip()
        text_len_diff = float(abs(len(text) - len(target['text'])))

        # 6. Sibling index diff
        sibling_index = get_sibling_index(element)
        sibling_index_diff = float(abs(sibling_index - target['sibling_index']))

        # 7. Class similarity (fuzzy match)
        elem_classes = element.get('class', [])
        if isinstance(elem_classes, str):
            elem_classes = elem_classes.split()
        elem_class_str = " ".join([c for c in elem_classes if c])
        target_class_str = " ".join(target['classes'])
        class_sim = fuzz.token_sort_ratio(elem_class_str, target_class_str) / 100.0

        # 8. ID similarity (fuzzy match)
        elem_id = element.get('id', '')
        if isinstance(elem_id, list):
            elem_id = " ".join(elem_id)
        id_sim = fuzz.ratio(elem_id, target['id']) / 100.0

        # 9. Attribute keys similarity
        elem_attrs = list(element.attrs.keys())
        common_attrs = set(elem_attrs).intersection(set(target['attrs']))
        union_attrs = set(elem_attrs).union(set(target['attrs']))
        attr_sim = len(common_attrs) / len(union_attrs) if union_attrs else 1.0

        # 10. Text content similarity
        text_sim = fuzz.token_set_ratio(text, target['text']) / 100.0

        return [
            is_same_tag,
            is_same_parent,
            child_count_diff,
            depth_diff,
            text_len_diff,
            sibling_index_diff,
            class_sim,
            id_sim,
            attr_sim,
            text_sim
        ]

    def learn_element(self, html_content: str, selector: str) -> bool:
        """
        Parses a golden (correct) HTML document, locates the target element
        using the selector, extracts its properties, and trains a RandomForest model.
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            target_el = soup.select_one(selector)
            if not target_el:
                logger.warning(f"Target element not found for selector: {selector}")
                return False

            # Extract target properties
            target_props = {
                'tag': target_el.name,
                'parent_tag': target_el.parent.name if target_el.parent else '',
                'child_count': len(target_el.find_all(recursive=False)),
                'depth': get_depth(target_el),
                'text': target_el.get_text().strip(),
                'id': target_el.get('id', '') or '',
                'classes': target_el.get('class', []) or [],
                'attrs': list(target_el.attrs.keys()),
                'sibling_index': get_sibling_index(target_el)
            }
            if isinstance(target_props['id'], list):
                target_props['id'] = " ".join(target_props['id'])
            if isinstance(target_props['classes'], str):
                target_props['classes'] = target_props['classes'].split()

            self.targets[selector] = target_props

            # Gather elements for dataset
            all_elements = soup.find_all()
            X = []
            y = []

            for el in all_elements:
                if not isinstance(el, Tag) or el.name in ['html', 'head', 'body', 'script', 'style']:
                    continue
                
                features = self.extract_relative_features(el, target_props)
                X.append(features)
                y.append(1 if el == target_el else 0)

            # Convert to numpy arrays
            X_arr = np.array(X)
            y_arr = np.array(y)

            # Fallback if only 1 sample or no negative samples
            if len(set(y_arr)) < 2:
                # Add a synthetic negative sample
                synthetic_neg = [0.0] * 10
                synthetic_neg[2] = 10.0  # highly different child count
                synthetic_neg[4] = 100.0  # highly different text length
                X_arr = np.vstack([X_arr, synthetic_neg])
                y_arr = np.append(y_arr, 0)

            # Train classifier
            clf = RandomForestClassifier(n_estimators=50, max_depth=5, class_weight='balanced', random_state=42)
            clf.fit(X_arr, y_arr)

            self.models[selector] = clf
            logger.info(f"Successfully learned DOM profile and trained model for selector: {selector}")
            return True

        except Exception as e:
            logger.error(f"Error learning element for selector {selector}: {e}", exc_info=True)
            return False

    def predict_selector(self, html_content: str, original_selector: str) -> Tuple[str, float]:
        """
        Attempts to locate the element using the original selector. If it fails,
        runs the trained classifier over candidates in the new HTML to find
        the most likely healed element and returns its new unique CSS selector
        and the confidence score (probability).
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 1. Quick path: does the original selector still work?
        target_el = soup.select_one(original_selector)
        if target_el:
            return original_selector, 1.0

        # 2. Selector is broken, try self-healing!
        if original_selector not in self.models or original_selector not in self.targets:
            logger.warning(f"No trained model or target profile found for selector: {original_selector}")
            return "", 0.0

        clf = self.models[original_selector]
        target_props = self.targets[original_selector]

        all_elements = soup.find_all()
        candidates: List[Tuple[Tag, List[float]]] = []

        for el in all_elements:
            if not isinstance(el, Tag) or el.name in ['html', 'head', 'body', 'script', 'style']:
                continue
            features = self.extract_relative_features(el, target_props)
            candidates.append((el, features))

        if not candidates:
            return "", 0.0

        # Extract features and predict probabilities
        X_test = np.array([features for _, features in candidates])
        probabilities = clf.predict_proba(X_test)[:, 1]  # Probabilities of class 1

        best_idx = int(np.argmax(probabilities))
        best_probability = float(probabilities[best_idx])
        best_element = candidates[best_idx][0]

        if best_probability > 0.5:
            healed_selector = generate_selector(best_element)
            logger.info(f"Self-healed selector '{original_selector}' -> '{healed_selector}' with confidence {best_probability:.4f}")
            return healed_selector, best_probability

        logger.warning(f"Self-healing failed for '{original_selector}'. Best match probability: {best_probability:.4f}")
        return "", best_probability
