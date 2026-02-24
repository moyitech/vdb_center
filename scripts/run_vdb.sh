docker run --name pgvector \
  --restart=always \
  -e POSTGRES_USER=pgvector \
  -e POSTGRES_PASSWORD=pgvector \
  -v vdb_centor_pgvector_data:/var/lib/postgresql \
  -p 5432:5432 \
  -d pgvector/pgvector:pg18-trixie