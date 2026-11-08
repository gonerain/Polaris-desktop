"""Example text transformations: independent instances, explicit App opt-in."""
import re
from polaris_platform.component import Component
from polaris_platform.protocol import PlatformError


def create(instance_context):
    component = Component()
    def text(params):
        value = params.get('text')
        if not isinstance(value, str) or len(value) > 200000:
            raise PlatformError('invalid_text', '请输入不超过二十万字符的文字')
        return value
    @component.operation('整理文本', provides='org.example.text.tidy@1', applicationBinding='instance')
    def tidy(params, context):
        value = text(params)
        lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in value.splitlines()]
        result = '\n'.join(line for line in lines if line)
        return dict(text=result, characters=len(result), origin=context.origin,
                    instanceId=instance_context['instanceId'])
    @component.operation('统计词频', provides='org.example.text.keywords@1', applicationBinding='instance')
    def keywords(params, context):
        value = text(params)
        words = re.findall(r'[A-Za-z][A-Za-z\-]{1,}|[\u4e00-\u9fff]{2,}', value)
        counts = {}
        for word in words:
            counts[word.lower()] = counts.get(word.lower(), 0) + 1
        ranked = sorted(counts, key=lambda word: (-counts[word], word))[:12]
        return dict(text='\n'.join(f'{word}  ·  {counts[word]}次' for word in ranked),
                    keywords=ranked, origin=context.origin, instanceId=instance_context['instanceId'])
    return component
