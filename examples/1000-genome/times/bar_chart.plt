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

# Set legend
set key noinvert box
set key left top vertical Left reverse noenhanced autotitle columnhead box lt black linewidth 1.000 dashtype solid
set key spacing 1.5

# Set X axis
set xtics border in scale 0,0 mirror norotate  autojustify
set xrange [0:500]
set xlabel "Cores"

# Set Y axis
set ytics border in scale 0,0 mirror norotate  autojustify
set yrange [0:*]
set ylabel "Strong scalability"

# Set line
set style line 1 linecolor rgb '#008FD0' linetype 1 linewidth 2 pointtype 5 pointsize 1.2
set style line 2 linecolor rgb '#FFC97D' linetype 1 linewidth 2 pointtype 5 pointsize 1.2

# Plot data
plot 'speedup.dat' using 1:2 with linespoints linestyle 1, '' using 1:3 with linespoints linestyle 2, x with linespoint lt 2 dt 2 pt 0 lc rgb '#828788'
