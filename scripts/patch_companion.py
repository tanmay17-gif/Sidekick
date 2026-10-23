path = r'c:\Users\Mrunal Amkar\OneDrive\Documents\Sidekick\web\src\components\Companion.tsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Eye whites on dark body look odd - make them the same dark blue so they blend in as subtle dots
content = content.replace('fill="#fffdf9" />', 'fill="#0e2240" />')
# Blue glowing pupils
content = content.replace('r="4.4" fill="#241f1b"', 'r="4.4" fill="#1a8fff" opacity="0.7"')
# Subtle cyan shimmer on top of orb body instead of bright white
content = content.replace('fill="#ffffff" opacity="0.2"', 'fill="#00d4ff" opacity="0.06"')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
