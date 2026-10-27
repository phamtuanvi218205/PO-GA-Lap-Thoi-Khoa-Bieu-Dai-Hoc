"""Cho phép chạy ứng dụng Python bằng ``python -m gapo_timetabling``."""

from .application.app_cli import main


raise SystemExit(main())
