# Print to EPS
set terminal eps font "libertine,14"

# Set borders
set boxwidth 0.75 absolute
set border 3 front lt black linewidth 1.000 dashtype solid
set style fill solid noborder

# Set grid
set grid nopolar
set grid noxtics nomxtics ytics nomytics noztics nomztics nortics nomrtics nox2tics nomx2tics noy2tics nomy2tics nocbtics nomcbtics
set grid layerdefault lt 0 linecolor 0 linewidth 0.500, lt 0 linecolor 0 linewidth 0.500

# Set histogram chart
set style histogram rowstacked title textcolor lt -1
set datafile missing '-'
set style data histograms

# Set legend
set key noinvert box
set key right top vertical Left reverse noenhanced autotitle columnhead box lt black linewidth 1.000 dashtype solid
set key spacing 1.5

# Set X axis
unset xtics
set xlabel "Slurm jobs"

# Set Y axis
set ytics border in scale 0,0 mirror norotate  autojustify
set yrange [0:*]
set ylabel "Time (min)"

# Plot data
plot 'times.dat' using 2 ti col lc rgb '#FFC97D', '' using 3 ti col lc rgb '#008FD0'
