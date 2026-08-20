#!/usr/bin/env python3
"""Test script to diagnose Qwen request formation."""

import sys
import io
from pathlib import Path

# Fix UTF-8 output for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

from document_assistant.core.settings import settings
from document_assistant.core.parsers import DataParser
from document_assistant.ai.encoders import TextEncoder
from document_assistant.ai.promt_builders import PromptEngine, NormativeBaseLoader
from document_assistant.ai.context_builder import ContextBuilder, NormativeIndex
from document_assistant.ai.preprocessor import DocumentChunker

print("=" * 80)
print("ТЕСТ ФОРМИРОВАНИЯ ЗАПРОСА НА QWEN")
print("=" * 80)
print()

# Paths - абсолютные пути!
from pathlib import Path as PathLib
normative_path = str(PathLib(__file__).parent / "dist" / "normative_base")
client_path = str(PathLib(__file__).parent / "tests" / "Техническое задание 2026-2027 v1.xlsx")

# Test 1: Load normative base
print("[1/5] Загрузка нормативной базы...")
print(f"  Путь: {normative_path}")
norm_loader = NormativeBaseLoader()
norm_text = norm_loader.load(normative_path)
print(f"  OK: Загружено {len(norm_text)} символов")
print(f"  Первые 200 символов: {norm_text[:200]}")
print()

# Test 2: Create NormativeIndex
print("[2/5] Создание NormativeIndex...")
norm_index = NormativeIndex(norm_text)
print(f"  OK: Разделов {norm_index.section_count}")
print(f"  Макс разделов (LLM_MAX_SECTIONS): {norm_index.MAX_SECTIONS}")
print()

# Test 3: Load client document
print("[3/5] Загрузка ТЗ клиента...")
print(f"  Путь: {client_path}")
parser = DataParser(client_path)
client_text = parser.origin_data(client_path)
print(f"  OK: Загружено {len(client_text)} символов")
print(f"  Первые 200 символов: {client_text[:200]}")
print()

# Test 4: Create PromptEngine
print("[4/5] Создание PromptEngine...")
prompt_engine = PromptEngine(
    role=settings.ai_role,
    template=settings.ai_prompt_template,
    normative_base=normative_path,
    num_ctx=settings.qwen_num_ctx,
)
print(f"  OK: PromptEngine создан")
print(f"  Разделов в индексе: {prompt_engine._norm_index.section_count}")
print(f"  Полный текст нормативной базы: {len(prompt_engine._norm_index.full_text)} символов")
print()

# Test 5: Build prompt
print("[5/5] Формирование промпта (build)...")
encoder = TextEncoder()
encoded_client = encoder.prepared_data(client_text)
print(f"  Закодировано клиентского текста: {len(encoded_client)} символов")

# Split into chunks
chunker = DocumentChunker(batch_size=settings.llm_batch_size)
chunks = chunker.split(encoded_client)
print(f"  Чанков: {len(chunks)}")
print()

# Build prompt for first chunk
if chunks:
    first_chunk = chunks[0]
    print(f"  Формирую промпт для первого чанка ({len(first_chunk)} символов)...")

    prompt = prompt_engine.build(
        source_text=first_chunk,
        examples=[]
    )

    print(f"  OK: Промпт создан {len(prompt)} символов")
    print()
    print("  Анализ промпта:")
    has_placeholder = '{normative_base}' in prompt
    has_text = norm_text[:50] in prompt if norm_text else False
    print(f"    - Содержит {{normative_base}}: {'ДА' if has_placeholder else 'НЕТ'}")
    print(f"    - Содержит нормативную базу текст: {'ДА' if has_text else 'НЕТ'}")
    print(f"    - Содержит {{role}}: {'ДА' if '{role}' in prompt else 'НЕТ'}")
    print(f"    - Содержит {{source_text}}: {'ДА' if '{source_text}' in prompt else 'НЕТ'}")
    print()

    # Show last 500 chars
    print("  ПОСЛЕДНИЕ 500 символов ПРОМПТА:")
    print("  " + "=" * 76)
    print("  " + prompt[-500:])
    print("  " + "=" * 76)
    print()

    # Test ContextBuilder directly
    print("[ДОПОЛНИТЕЛЬНО] Тест ContextBuilder.build()...")
    ctx_builder = prompt_engine._context_builder
    print(f"  Макс доступно символов: {ctx_builder._max_chars}")
    print(f"  Полный текст нормативной базы: {len(ctx_builder._index.full_text)} символов")

    full_norm = ctx_builder._index.full_text
    print(f"  OK: full_text загружен {len(full_norm)} chars, first 100: {full_norm[:100]}")
    print()

print("=" * 80)
print("ТЕСТ ЗАВЕРШЁН")
print("=" * 80)
