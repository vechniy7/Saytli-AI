"""Visual art-direction systems used to make generated sites distinct."""
SYSTEMS = {
  'restaurant': {'id':'luxury-restaurant','palette':'ink #15110f, warm cream #f6f0e7, burgundy #7d2638, brass #c6a36b','type':'editorial serif headlines + neutral sans body','layout':'asymmetric editorial hero, menu sections, image-led dish cards','motion':'gentle reveal, image zoom, reduced-motion support','images':'warm candlelit food photography, close crops, avoid generic gradients','avoid':'dark SaaS dashboard look, repeated pill cards'},
  'fashion': {'id':'editorial-fashion','palette':'milk #f4f0e9, black #161616, cobalt #244fe5, muted gray','type':'high-contrast fashion serif + geometric sans','layout':'asymmetric lookbook grid, oversized campaign image, product rails','motion':'quiet image transitions, editorial hover, reduced-motion support','images':'fashion editorial, studio and streetwear photography, consistent art direction','avoid':'restaurant palette, generic ecommerce template'},
  'portfolio': {'id':'studio-portfolio','palette':'warm white, graphite, one electric accent selected to fit brief','type':'distinctive display face + readable sans','layout':'bold identity hero, project case-study grid, generous whitespace','motion':'subtle section reveals and project hover','images':'project imagery or custom CSS artwork','avoid':'fake metrics, repetitive feature cards'},
  'generic': {'id':'modern-editorial','palette':'choose 3 coordinated colors from brief','type':'display headline + highly readable body face','layout':'strong asymmetry, clear hierarchy, content-specific sections','motion':'restrained micro-interactions, reduced-motion support','images':'select subject-specific imagery, avoid unrelated stock','avoid':'generic purple gradient, identical pill/card grids'}
}

def select_design_system(skill_names):
    if 'restaurant' in skill_names: return SYSTEMS['restaurant']
    if 'fashion' in skill_names or 'ecommerce' in skill_names: return SYSTEMS['fashion']
    if 'portfolio' in skill_names: return SYSTEMS['portfolio']
    return SYSTEMS['generic']
