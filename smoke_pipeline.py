from design_systems import select_design_system
from pipeline import static_review
print(select_design_system(['services'])['id'])
print(select_design_system(['project'])['id'])
print(static_review('<!doctype html><html><head><title>Portfolio</title><meta name="viewport" content="width=device-width"></head><body><header>Header</header><main><section>'+('x'*300)+'</section></main><footer>Footer</footer><style>@media (min-width:1px){}</style><script>document.querySelector("header").addEventListener("click", function(){});</script></body></html>')['score'])
