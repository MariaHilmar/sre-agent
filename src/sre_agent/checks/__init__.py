"""Checks de saúde.

Fase 0 traz o `http` (Camada 1 do runbook: GET /health). As próximas fases
adicionam checks via API de plataforma (Railway, Vercel, Supabase, GitHub),
cada um como um novo módulo aqui, sem tocar no núcleo.
"""
