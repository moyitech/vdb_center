class ProjectService:
    async def get_project_list(self) -> list[dict]:
        from src.db.database import DBSession
        from src.db.mapper import get_project_list as mapper_get_project_list

        async with DBSession() as session:
            return await mapper_get_project_list(session)
