import dataframe_image as dfi
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt

plt.rcParams['font.family'] = 'Noto Sans TC'
# matplotlib.rcParams['font.family'] = 'Noto Sans TC'
matplotlib.rcParams['font.sans-serif'] = 'DejaVu Sans'

print("===字型路徑", matplotlib.matplotlib_fname())

# Create a DataFrame
df = pd.DataFrame({
    'Country': ['台灣', '加拿大', '墨西哥'],
    'Capital': ['Washington D.C.', 'Ottawa', 'Mexico City'],
    'Population': [3.28200000, 37.590000, 12.6200000]
})

# idx = pd.IndexSlice
# slice_ = idx[idx[:,'r2'], :]
# df = df.style.hide_index()
# df_style = df.style.background_gradient()
df_style = df.style\
    .apply(lambda x: ['background-color: #ddfada' if ((x.name+1)%2) else '' for i in x], axis=1)\
    .hide(axis="index")

# df_style = df.style.set_properties(**{'background-color': 'black', 'color': 'green'})
# df_style = df.style.format('{:.1f}')

# Save DataFrame as an image
# dfi.export(df.style.hide(axis="index"), 'dataframe.jpg', dpi=150, table_conversion='matplotlib')
dfi.export(df_style, 'dataframe.jpg', table_conversion='matplotlib')

#  Glyph 22696 (\N{CJK UNIFIED IDEOGRAPH-58A8}) missing from font(s) DejaVu Sans.
