from app.config import settings


def main() -> None:
    print(f"{settings.app_name} ready")


if __name__ == "__main__":
    main()
