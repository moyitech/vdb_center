from sqlalchemy import func

def make_fts(tokens: list[str]):
    token_text = " ".join(tokens)          # 例如: "机器 学习 机器学习 很好"
    return func.to_tsvector("simple", token_text)

# 插入时
print(make_fts(['机器', '学习', '机器学习', '很好']))