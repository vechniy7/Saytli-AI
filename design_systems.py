"""Visual art-direction systems used to make generated sites distinct."""
SYSTEMS = {
  'portfolio': {'id':'studio-portfolio','palette':'warm white, graphite, one electric accent selected to fit brief','type':'distinctive display face + readable sans','layout':'bold identity hero, project case-study grid, generous whitespace','motion':'subtle section reveals and project hover','images':'project imagery or custom CSS artwork','avoid':'fake metrics, repetitive feature cards'},
  'services': {'id':'clear-service-studio','palette':'soft neutral base, graphite text, one confident accent','type':'humanist sans with a restrained display face','layout':'clear offer hero, service cards, process timeline, contact CTA','motion':'quiet reveals, clear hover/focus states','images':'work detail or CSS visuals relevant to the specialist','avoid':'generic SaaS dashboard, invented proof'},
  'project': {'id':'product-story','palette':'deep ink, warm white, one bright technical accent','type':'strong contemporary sans with readable body copy','layout':'problem-to-solution story, feature highlights, project principles, contact CTA','motion':'restrained transitions, reduced-motion support','images':'product visuals or CSS artwork, no fake screenshots','avoid':'pricing tables, fake metrics, dashboard clutter'},
  'generic': {'id':'modern-editorial','palette':'choose 3 coordinated colors from brief','type':'display headline + highly readable body face','layout':'strong asymmetry, clear hierarchy, content-specific sections','motion':'restrained micro-interactions, reduced-motion support','images':'select subject-specific imagery, avoid unrelated stock','avoid':'generic purple gradient, identical pill/card grids'}
}

def select_design_system(skill_names):
    if 'services' in skill_names or 'business' in skill_names: return SYSTEMS['services']
    if 'project' in skill_names: return SYSTEMS['project']
    if 'portfolio' in skill_names or 'case-study' in skill_names: return SYSTEMS['portfolio']
    return SYSTEMS['generic']
