program avg
  implicit none
  ! Naive legacy example: reads integers from STDIN and computes an average.
  ! Limitations to observe for the architecture review:
  ! - Reads only integers (won't handle decimals)
  ! - Uses integer division when computing the mean
  ! - No CSV parsing, header handling, or file I/O via arguments
  integer :: x
  integer :: sum, count
  real :: mean
  sum = 0
  count = 0
  print *, 'Reading integers from STDIN...'
  do
     read(*,*, end=100) x
     sum = sum + x
     count = count + 1
  end do
100 continue
  if (count > 0) then
     mean = sum / count  ! integer division truncation
  else
     mean = 0.0
  end if
  print *, 'Count=', count
  print *, 'Mean=', mean
end program avg
