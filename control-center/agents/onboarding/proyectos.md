## Apartado: Proyectos (id `proyectos`)
Configuración `github` = `{"owner": "usuario-u-organizacion", "repos": {"nombre-repo": {"area": "trabajo", "modelo": "sonnet", "minutos": 45, "subagentes": false}}}`.
- Requiere `gh` autenticado en el PC (`gh auth login`, lo hace él).
- Pregunta la cuenta u organización y qué repos quiere seguir; clónalas él en `repos/` (o se clonan al primer encargo).
- El programador trabaja solo en la rama `staging` y nunca hace push: lo sube el PC y abre un PR.
