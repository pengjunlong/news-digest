---
layout: news-list
title: 新闻存档
pagination:
  enabled: true
  collection: posts
  per_page: 10
---

{% for post in paginator.posts %}
## [{{ post.title }}]({{ post.url }})
{{ post.date | date: "%Y-%m-%d" }}
{{ post.excerpt }}
{% endfor %}

<!-- 分页导航 -->
<div class="pagination">
  {% if paginator.previous_page %}
    <a href="{{ paginator.previous_page_path }}">上一页</a>
  {% endif %}

<span>第 {{ paginator.page }} 页 / 共 {{ paginator.total_pages }} 页</span>

{% if paginator.next_page %}
<a href="{{ paginator.next_page_path }}">下一页</a>
{% endif %}
</div>
