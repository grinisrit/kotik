#include <iostream>
#include <cstdlib>
#include <TNL/Containers/Vector.h>
#include <TNL/Algorithms/reduce.h>

using namespace TNL;
using namespace TNL::Containers;
using namespace TNL::Algorithms;

template< typename Device >
double sum( const Vector< double, Device >& v )
{
   /****
    * Get vector view which can be captured by lambda.
    */
   auto view = v.getConstView();

   /****
    * The fetch function just reads elements of vector v.
    */
   auto fetch = [=] __cuda_callable__ ( int i ) -> double { return view[ i ]; };

   /***
    * Finally we call the templated function Reduction and pass number of elements to reduce,
    * lambda defined above and functional representing the reduction operation.
    */
   return reduce< Device >( 0, view.getSize(), fetch, TNL::Plus{} );
}

int main( int argc, char* argv[] )
{
   /***
    * Firstly, test the sum with vectors allocated on CPU.
    */
   Vector< double, Devices::Host > host_v( 10 );
   host_v = 1.0;
   std::cout << "host_v = " << host_v << std::endl;
   std::cout << "The sum of the host vector elements is " << sum( host_v ) << "." << std::endl;

   /***
    * And then also on GPU.
    */
#ifdef HAVE_CUDA
   Vector< double, Devices::Cuda > cuda_v( 10 );
   cuda_v = 1.0;
   std::cout << "cuda_v = " << cuda_v << std::endl;
   std::cout << "The sum of the CUDA vector elements is " << sum( cuda_v ) << "." << std::endl;
#endif
   return EXIT_SUCCESS;
}

