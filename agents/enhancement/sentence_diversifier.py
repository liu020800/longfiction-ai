import re
import logging

logger = logging.getLogger(__name__)


class SentenceDiversifier:
    def __init__(self):
        self.patterns = {
            "svo": re.compile(r'[他她它我你][^，。！？]{2,10}[了着过]'),
            "passive": re.compile(r'被[^，。！？]{2,10}了'),
            "inverted": re.compile(r'^[^他她它我你]{1,5}[，,][他她它我你]'),
        }

    def detect_consecutive_same(self, text: str) -> list[tuple[int, int, str]]:
        sentences = re.split(r'([。！？])', text)
        clean_sentences = []
        for i in range(0, len(sentences) - 1, 2):
            s = sentences[i].strip()
            if s and len(s) > 5:
                clean_sentences.append(s)

        if len(clean_sentences) < 3:
            return []

        results = []
        struct_labels = [self._classify_structure(s) for s in clean_sentences]

        i = 0
        while i < len(struct_labels):
            j = i + 1
            while j < len(struct_labels) and struct_labels[j] == struct_labels[i] and struct_labels[i] != "mixed":
                j += 1
            if j - i >= 3:
                results.append((i, j - 1, struct_labels[i]))
            i = j

        return results

    def diversify(self, text: str) -> str:
        consecutive = self.detect_consecutive_same(text)
        if not consecutive:
            return text

        sentences = re.split(r'([。！？])', text)
        parts = []
        i = 0
        while i < len(sentences):
            parts.append(sentences[i])
            if i + 1 < len(sentences) and sentences[i + 1] in '。！？':
                parts.append(sentences[i + 1])
                i += 2
            else:
                i += 1

        modified = list(parts)
        for start, end, struct_type in consecutive:
            mid_idx = (start + end) // 2
            if mid_idx < len(modified):
                sentence = modified[mid_idx]
                transformed = self._transform_sentence(sentence, struct_type)
                if transformed != sentence:
                    modified[mid_idx] = transformed

        return "".join(modified)

    def _classify_structure(self, sentence: str) -> str:
        has_svo = bool(self.patterns["svo"].search(sentence[:15]))
        has_passive = bool(self.patterns["passive"].search(sentence))
        has_dialogue = any(q in sentence for q in ['\u201c', '\u201d', '"', '「', '」'])
        if has_dialogue:
            return "dialogue"
        if has_svo and not has_passive:
            return "svo"
        if has_passive:
            return "passive"
        return "mixed"

    def _transform_sentence(self, sentence: str, struct_type: str) -> str:
        if struct_type == "svo":
            comma_pos = sentence.find('，')
            if comma_pos > 0 and comma_pos < len(sentence) - 1:
                return sentence[comma_pos + 1:] + '，' + sentence[:comma_pos]
        elif struct_type == "passive":
            sentence = sentence.replace('被', '遭', 1)
        return sentence
